import os
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# Load environment variables
load_dotenv()

# Get sensitive information from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")

# States for conversation handler
NAME, CONTACT, INTRODUCTION, PROJECT_NAME, PROJECT_LINK, PROJECT_DOC, ANOTHER_PROJECT = range(7)

# Dictionary to store user data temporarily
user_data = {}


class PortfolioBot:
    def __init__(self, telegram_token, credentials_path):
        # Initialize Google Sheets credentials
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
        self.gc = gspread.authorize(credentials)

        # Open the spreadsheet (create one if it doesn't exist)
        try:
            self.sheet = self.gc.open("Portfolio Submissions").sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            spreadsheet = self.gc.create("Portfolio Submissions")
            self.sheet = spreadsheet.sheet1
            spreadsheet.share(credentials.service_account_email, perm_type='user', role='writer')
            print(f"Spreadsheet created: {spreadsheet.url}")
            # Add headers
            headers = ["Timestamp", "Name", "Contact", "Introduction", "Projects"]
            self.sheet.append_row(headers)

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
                ANOTHER_PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.ask_another_project)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
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
        """Store name and ask for contact details."""
        user_id = update.message.from_user.id
        user_data[user_id]['name'] = update.message.text

        await update.message.reply_text("Great! Now please share your contact details (email/phone):")
        return CONTACT

    async def get_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Store contact and ask for introduction."""
        user_id = update.message.from_user.id
        user_data[user_id]['contact'] = update.message.text

        await update.message.reply_text("Please provide a brief introduction about yourself:")
        return INTRODUCTION

    async def get_introduction(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Store introduction and ask for project name."""
        user_id = update.message.from_user.id
        user_data[user_id]['introduction'] = update.message.text

        await update.message.reply_text("Now, let's add your projects. What's the name of your project?")
        return PROJECT_NAME

    async def get_project_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Store project name and ask for project link."""
        user_id = update.message.from_user.id
        user_data[user_id]['current_project'] = {'name': update.message.text}

        await update.message.reply_text("Please provide the link to your project:")
        return PROJECT_LINK

    async def get_project_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Store project link and ask for documentation."""
        user_id = update.message.from_user.id
        user_data[user_id]['current_project']['link'] = update.message.text

        await update.message.reply_text("Please provide documentation or description for this project:")
        return PROJECT_DOC

    async def get_project_doc(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Store project documentation and ask if user wants to add another project."""
        user_id = update.message.from_user.id
        user_data[user_id]['current_project']['documentation'] = update.message.text

        user_data[user_id]['projects'].append(user_data[user_id]['current_project'])

        reply_keyboard = [['Yes', 'No']]
        await update.message.reply_text(
            "Would you like to add another project?",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
        )
        return ANOTHER_PROJECT

    async def ask_another_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle response about adding another project."""
        if update.message.text.lower() == 'yes':
            await update.message.reply_text(
                "What's the name of your next project?",
                reply_markup=ReplyKeyboardRemove(),
            )
            return PROJECT_NAME
        else:
            user_id = update.message.from_user.id
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            projects_formatted = "\n".join(
                [
                    f"Project: {p['name']}\nLink: {p['link']}\nDoc: {p['documentation']}\n"
                    for p in user_data[user_id]['projects']
                ]
            )

            row_data = [
                timestamp,
                user_data[user_id]['name'],
                user_data[user_id]['contact'],
                user_data[user_id]['introduction'],
                projects_formatted,
            ]

            self.sheet.append_row(row_data)
            del user_data[user_id]

            await update.message.reply_text(
                "Thank you! Your portfolio information has been saved.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        user_id = update.message.from_user.id
        if user_id in user_data:
            del user_data[user_id]

        await update.message.reply_text(
            "Operation cancelled. Your data was not saved.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    def run(self):
        """Run the bot."""
        self.application.run_polling()


if __name__ == "__main__":
    bot = PortfolioBot(TELEGRAM_TOKEN, GOOGLE_CREDENTIALS_PATH)
    bot.run()
