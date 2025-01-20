import os
import logging
import time
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# Set up logging with more detailed format
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "10"))

if not TELEGRAM_TOKEN or not GOOGLE_CREDENTIALS_PATH:
    raise ValueError("Missing required environment variables. Please check your .env file.")

# States for conversation handler
NAME, CONTACT, INTRODUCTION, PROJECT_NAME, PROJECT_LINK, PROJECT_DOC, ANOTHER_PROJECT = range(7)

# Dictionary to store user data temporarily
user_data = {}


class PortfolioBot:
    def __init__(self, telegram_token, credentials_path):
        self.telegram_token = telegram_token
        self.credentials_path = credentials_path
        self.initialize_google_sheets()
        self.initialize_bot()
        logger.info("Bot initialized successfully")

    def initialize_google_sheets(self):
        """Initialize Google Sheets with retry mechanism"""
        retry_count = 0
        while retry_count < MAX_RETRIES:
            try:
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                credentials = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_path, scope)
                self.gc = gspread.authorize(credentials)

                try:
                    self.sheet = self.gc.open("Portfolio Submissions").sheet1
                except:
                    spreadsheet = self.gc.create("Portfolio Submissions")
                    self.sheet = spreadsheet.sheet1
                    logger.info(f"Spreadsheet created: {spreadsheet.url}")
                    headers = ["Timestamp", "Name", "Contact", "Introduction", "Project Name", "Project Link",
                               "Project Doc"]
                    self.sheet.append_row(headers)

                logger.info("Google Sheets connection established successfully")
                return
            except Exception as e:
                retry_count += 1
                logger.error(f"Attempt {retry_count} failed to initialize Google Sheets: {e}", exc_info=True)
                if retry_count < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    raise

    def initialize_bot(self):
        """Initialize the Telegram bot application"""
        self.application = Application.builder().token(self.telegram_token).build()

        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_contact)],
                INTRODUCTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_introduction)],
                PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_project_name)],
                PROJECT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_project_link)],
                PROJECT_DOC: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_project_doc)],
                ANOTHER_PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.ask_another_project)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )

        self.application.add_handler(conv_handler)
        logger.info("Bot handlers initialized successfully")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask for user's name."""
        user_id = update.message.from_user.id
        user_data[user_id] = {'projects': []}

        await update.message.reply_text(
            "Gm Gm \n\n"
            "Hi! I'm the Portfolio Collection Bot. Let's gather your information.\n\n"
            "Please enter your full name:"
        )
        return NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save user's name and ask for contact information."""
        user_id = update.message.from_user.id
        user_data[user_id]['name'] = update.message.text

        await update.message.reply_text("Please enter your contact information (email or phone number):")
        return CONTACT

    async def get_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save user's contact information and ask for an introduction."""
        user_id = update.message.from_user.id
        user_data[user_id]['contact'] = update.message.text

        await update.message.reply_text("Please provide a brief introduction about yourself:")
        return INTRODUCTION

    async def get_introduction(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save user's introduction and ask for their project name."""
        user_id = update.message.from_user.id
        user_data[user_id]['introduction'] = update.message.text

        await update.message.reply_text("Please enter the name of your project:")
        return PROJECT_NAME

    async def get_project_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save project name and ask for project link."""
        user_id = update.message.from_user.id
        project = {'name': update.message.text}
        user_data[user_id]['projects'].append(project)

        await update.message.reply_text("Please enter the link to your project:")
        return PROJECT_LINK

    async def get_project_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save project link and ask for project documentation."""
        user_id = update.message.from_user.id
        project = user_data[user_id]['projects'][-1]
        project['link'] = update.message.text

        await update.message.reply_text("Please provide documentation or a description of your project:")
        return PROJECT_DOC

    async def get_project_doc(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save project documentation and ask if the user has another project."""
        user_id = update.message.from_user.id
        project = user_data[user_id]['projects'][-1]
        project['doc'] = update.message.text

        await update.message.reply_text("Would you like to add another project? (yes/no)")
        return ANOTHER_PROJECT

    async def ask_another_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle response about adding another project."""
        user_id = update.message.from_user.id
        response = update.message.text.lower()

        if response == 'yes':
            await update.message.reply_text("Please enter the name of your next project:")
            return PROJECT_NAME
        else:
            try:
                await self.save_to_sheet(user_id)
                await update.message.reply_text("Thank you! Your information has been saved.")
            except Exception as e:
                logger.error(f"Failed to save data: {e}", exc_info=True)
                await update.message.reply_text("There was an error saving your information. Please try again later.")
            finally:
                user_data.pop(user_id, None)
            return ConversationHandler.END

    async def save_to_sheet(self, user_id):
        """Save user data to Google Sheets with retry mechanism."""
        retry_count = 0
        while retry_count < MAX_RETRIES:
            try:
                data = user_data[user_id]
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                for project in data['projects']:
                    row = [
                        timestamp,
                        data['name'],
                        data['contact'],
                        data['introduction'],
                        project['name'],
                        project['link'],
                        project['doc']
                    ]
                    self.sheet.append_row(row)
                logger.info(f"Successfully saved data for user {user_id}")
                return
            except Exception as e:
                retry_count += 1
                logger.error(f"Attempt {retry_count} failed to save to sheet: {e}", exc_info=True)
                if retry_count < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    raise

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        user_id = update.message.from_user.id
        user_data.pop(user_id, None)
        await update.message.reply_text("The process has been canceled. Have a great day!")
        return ConversationHandler.END

    def run_flask(self):
        """Run a simple Flask app for port binding with health check."""
        try:
            app = Flask(__name__)

            @app.route('/')
            def hello():
                return "Hello, I'm the Portfolio Bot!"

            @app.route('/health')
            def health():
                # Add basic health checks
                try:
                    # Check Google Sheets connection
                    self.sheet.row_count
                    return "OK", 200
                except Exception as e:
                    logger.error(f"Health check failed: {e}", exc_info=True)
                    return "Service Unavailable", 503

            port = int(os.getenv('PORT', 10000))
            logger.info(f"Starting Flask server on port {port}")
            app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"Failed to start Flask server: {e}", exc_info=True)
            raise

    def run(self):
        """Run the bot and Flask server with improved error handling and event loop management."""
        try:
            # Start the Flask app in a separate thread
            flask_thread = Thread(target=self.run_flask)
            flask_thread.daemon = True
            flask_thread.start()
            logger.info("Flask thread started")

            # Run the bot with automatic reconnection
            while True:
                try:
                    logger.info("Starting bot polling...")
                    # Create a new event loop for each attempt
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Reinitialize the application for each attempt
                    self.application = Application.builder().token(self.telegram_token).build()

                    # Re-add the conversation handler
                    conv_handler = ConversationHandler(
                        entry_points=[CommandHandler('start', self.start)],
                        states={
                            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_contact)],
                            INTRODUCTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_introduction)],
                            PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_project_name)],
                            PROJECT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_project_link)],
                            PROJECT_DOC: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_project_doc)],
                            ANOTHER_PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.ask_another_project)]
                        },
                        fallbacks=[CommandHandler('cancel', self.cancel)]
                    )
                    self.application.add_handler(conv_handler)

                    # Run the application with the new event loop
                    self.application.run_polling(drop_pending_updates=True)

                except Exception as e:
                    logger.error(f"Bot polling stopped: {e}", exc_info=True)
                    logger.info(f"Attempting to restart in {RETRY_DELAY} seconds...")

                    # Clean up the event loop
                    try:
                        loop.stop()
                        loop.close()
                    except Exception as loop_error:
                        logger.error(f"Error closing event loop: {loop_error}", exc_info=True)

                    time.sleep(RETRY_DELAY)

                finally:
                    # Ensure the event loop is closed
                    try:
                        if loop and not loop.is_closed():
                            loop.close()
                    except Exception as cleanup_error:
                        logger.error(f"Error in final cleanup: {cleanup_error}", exc_info=True)

        except Exception as e:
            logger.error(f"Critical error in main loop: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            logger.info("Initializing Portfolio Bot...")
            bot = PortfolioBot(TELEGRAM_TOKEN, GOOGLE_CREDENTIALS_PATH)
            bot.run()
        except Exception as e:
            retry_count += 1
            logger.error(f"Attempt {retry_count} failed to start bot: {e}", exc_info=True)
            if retry_count < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error("Max retries reached. Shutting down.")
                raise