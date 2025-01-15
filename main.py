import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")

if not TELEGRAM_TOKEN or not GOOGLE_CREDENTIALS_PATH:
    raise ValueError("Missing required environment variables. Please check your .env file.")

# States for conversation handler
NAME, CONTACT, INTRODUCTION, PROJECT_NAME, PROJECT_LINK, PROJECT_DOC, ANOTHER_PROJECT = range(7)

# Dictionary to store user data temporarily
user_data = {}


class PortfolioBot:
    def __init__(self, telegram_token, credentials_path):
        # Initialize Google Sheets credentials
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            credentials = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
            self.gc = gspread.authorize(credentials)

            # Open the spreadsheet (create one if it doesn't exist)
            try:
                self.sheet = self.gc.open("Portfolio Submissions").sheet1
            except:
                spreadsheet = self.gc.create("Portfolio Submissions")
                self.sheet = spreadsheet.sheet1
                logger.info(f"Spreadsheet created: {spreadsheet.url}")
                # Add headers
                headers = ["Timestamp", "Name", "Contact", "Introduction", "Project Name", "Project Link",
                           "Project Doc"]
                self.sheet.append_row(headers)
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
            raise

        # Initialize bot application
        self.application = Application.builder().token(telegram_token).build()

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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask for user's name."""
        user_id = update.message.from_user.id
        user_data[user_id] = {'projects': []}

        await update.message.reply_text(
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
            await self.save_to_sheet(user_id)
            await update.message.reply_text("Thank you! Your information has been saved.")
            user_data.pop(user_id, None)
            return ConversationHandler.END

    async def save_to_sheet(self, user_id):
        """Save user data to Google Sheets."""
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

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        user_id = update.message.from_user.id
        user_data.pop(user_id, None)
        await update.message.reply_text("The process has been canceled. Have a great day!")
        return ConversationHandler.END

    def run(self):
        """Run the bot and Flask server in separate threads."""
        try:
            # Start the Flask app in a separate thread
            flask_thread = Thread(target=self.run_flask)
            flask_thread.daemon = True
            flask_thread.start()

            # Start the Telegram bot in the main thread
            logger.info("Starting bot...")
            self.application.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Failed to start the bot: {e}")
            raise

    def run_flask(self):
        """Run a simple Flask app for port binding."""
        try:
            app = Flask(__name__)

            @app.route('/')
            def hello():
                return "Hello, I'm the Portfolio Bot!"

            port = int(os.getenv('PORT', 10000))
            app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"Failed to start Flask server: {e}")
            raise


if __name__ == "__main__":
    try:
        bot = PortfolioBot(TELEGRAM_TOKEN, GOOGLE_CREDENTIALS_PATH)
        bot.run()
    except Exception as e:
        logger.error(f"Failed to initialize or run the bot: {e}")
        raise