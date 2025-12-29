import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from openai import OpenAI
import httpx
from datetime import datetime
import json
import re
from database import Database

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
class DebtBot:
    def __init__(self):
        self.db = db
        self.pending_debts = {}
        self.user_context = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.create_user(user.id, user.username, user.first_name, user.last_name)
        if user.username:
            self.db.link_pending_debts(f'@{user.username}', user.id)
        
        keyboard = [[KeyboardButton("💰 Men qarzdorman"), KeyboardButton("💵 Menga qarzlar")],
                    [KeyboardButton("📜 Tarix"), KeyboardButton("📊 Statistika")],
                    [KeyboardButton("ℹ️ Yordam")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_text = (f"👋 Salom, {user.first_name}!\n\n"
                       "Men Telegram orqali qarzlar va umumiy xarajatlarni boshqarish botiman.\n\n"
                       "🎤 *Ovozli xabar yuboring* va men:\n"
                       "• Qarz yoki xarajatni qayd qilaman\n"
                       "• Ishtirokchilarni bog'layman\n"
                       "• Tasdiqlash so'rayman\n"
                       "• Barcha ishtirokchilarga xabar beraman\n\n"
                       "📝 *Misollar:*\n"
                       '• "Alisher menga 50 ming so\'m qarz berdi lunch uchun"\n'
                       '• "Men Dilnozaga 100 ming so\'m qarz berdim"\n\n'
                       "Ovozli xabar yuboring!")
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)    
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = ("📖 *Yordam*\n\n"
                    "*Qarz yaratish:*\n"
                    "🎤 Ovozli xabar yuboring\n\n"
                    "*Tugmalar:*\n"
                    "📊 Mening qarzlarim - Barcha qarzlar\n"
                    "💰 Men qarzdorman - Men to'lashim kerak\n"
                    "💵 Menga qarzlar - Menga to'lashlari kerak\n"
                    "📜 Tarix - To'liq tarix\n"
                    "📊 Statistika - Statistika")
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        processing_msg = await update.message.reply_text("🎤 Ovozli xabaringizni tinglayapman...")
        
        try:
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)
            voice_path = f"voice_{user.id}_{datetime.now().timestamp()}.ogg"
            await file.download_to_drive(voice_path)
        
            with open(voice_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(model="whisper-1",file=audio_file)
            transcribed_text = transcript.text
            if os.path.exists(voice_path):
                os.remove(voice_path)
            
            await processing_msg.edit_text(f"📝 Matn: _{transcribed_text}_\n\n⏳ Tahlil qilyapman...", parse_mode='Markdown')
            
            debt_info = await self.parse_debt_info(transcribed_text, user)
            
            if debt_info.get('clarification_needed'):
                # Store context for clarification response
                self.user_context[user.id] = {
                    'action': 'clarification',
                    'original_text': transcribed_text,
                    'processing_msg_id': processing_msg.message_id
                }
                await processing_msg.edit_text(debt_info['clarification_question'])
                return
            
            if debt_info.get('error'):
                await processing_msg.edit_text(f"❌ {debt_info['error']}\n\nIltimos, qaytadan urinib ko'ring.")
                return
            
            if debt_info.get('is_group'):
                self.user_context[user.id] = {
                    'action': 'split_type',
                    'debt_info': debt_info,
                    'processing_msg_id': processing_msg.message_id
                }
                keyboard = [
                    [InlineKeyboardButton("🟰 Teng bo'lish", callback_data="split_equal")],
                    [InlineKeyboardButton("📊 Turli bo'lish", callback_data="split_unequal")]
                ]
                await processing_msg.edit_text("❓ Umumiy xarajatlarni qanday bo'lish kerak?", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            missing = self.check_missing_info(debt_info)
            if missing:
                await self.request_missing_info(update, context, debt_info, missing, processing_msg)
                return
            
            await self.create_debt_confirmation(update, context, debt_info, processing_msg)
            
        except Exception as e:
            logger.error(f"Error processing voice: {e}")
            await processing_msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)[:100]}")
    
    async def parse_debt_info(self, text: str, user):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[

                    {"role": "system", "content": """Sen qarz va umumiy xarajatlarni tahlil qiluvchi AI yordamchisan. Matn o'zbek, rus va ingliz tillarida aralash bo'lishi mumkin.

                    VAZIFA: Matndan qarz yoki umumiy xarajat ma'lumotlarini chiqarib ol va JSON formatida qaytaring.

                    UMUMIY XARAJAT (Group Expense):
                    Agar matn umumiy xarajat haqida bo'lsa (bir kishi to'lagan, boshqalar bo'lishishi kerak), qaytaring:
                    {
                        "is_group": true,
                        "payer_name": "to'lovchi ism yoki Men",
                        "participants": ["ism1", "ism2", "Men"],
                        "total_amount": raqam,
                        "reason": "sabab",
                        "currency": "som"
                    }

                    MUHIM: participants ro'yxatida to'lovchini ham qo'shing! Agar "man" yoki "men" aytilsa, "Men" deb saqlang.

                    Misollar:
                    - "Bugun obedda 230000 toladim. Murod, Ibrohim va man" -> is_group: true, payer_name: "Men", participants: ["Murod", "Ibrohim", "Men"], total_amount: 230000
                    - "Kafe uchun 150 ming toladim Dilnoza bilan" -> is_group: true, payer_name: "Men", participants: ["Dilnoza", "Men"], total_amount: 150000
                    - "300 ming toldim 5 kishi bilan" -> is_group: true, payer_name: "Men", participants: ["Men"], total_amount: 300000 (5 kishi nomi yo'q, keyinroq so'raladi)

                    ODDIY QARZ (Simple Debt):
                    Agar oddiy qarz bo'lsa (2 kishi ortasida), qaytaring:
                    {
                        "amount": raqam,
                        "currency": "som",
                        "creditor_name": "qarz beruvchi",
                        "debtor_name": "qarz oluvchi",
                        "reason": "sabab",
                        "direction": "i_owe yoki owe_me"
                    }

                    Qoidalar:
                    - "menga qarz berdi" yoki "mne dal" = direction: "owe_me"
                    - "men qarz berdim" yoki "ya dal" = direction: "i_owe"
                    - "qarzdor" yoki "dolzhen" = direction: "owe_me"

                    ANIQ EMAS (Clarification Needed):
                    Agar malumot yetarli emas yoki noaniq bolsa:
                    {
                        "clarification_needed": true,
                        "clarification_question": "Aniq savol (ozbekcha)"
                    }

                    Savollar: Kim toladi?, Jami qancha?, Kimlar bilan?, Qanday bolish kerak?

                    RAQAMLAR:
                    - "50 ming" = 50000
                    - "150 min" = 150000
                    - "230000" = 230000
                    - "230.000" = 230000
                    - Nuqta va vergulni ignore qiling

                    ISMLAR:
                    - "man", "men", "ya" = "Men"
                    - Rus va ozbek ismlari: Murod, Ibrohim, Asadbek, Dilnoza, Gulbahor
                    - Username: @username formatida saqlang

                    MUHIM: Faqat JSON qaytaring, boshqa matn yoq!"""},
                    {"role": "user", "content": text}
                ],
                temperature=0.3
            )
            
            content = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:].strip()
            
            result = json.loads(content)
            result['original_text'] = text
            return result
        except Exception as e:
            logger.error(f"Parse error: {e}")
            logger.error(f"Full error details: {type(e).__name__}: {str(e)}")
            return {'error': f'Tushunmadim. Xato: {str(e)[:50]}'}
    
    def check_missing_info(self, debt_info):
        missing = []
        if not debt_info.get('amount'):
            missing.append('amount')
        direction = debt_info.get('direction')
        if direction == 'owe_me' and not debt_info.get('creditor_name'):
            missing.append('creditor_name')
        elif direction == 'i_owe' and not debt_info.get('debtor_name'):
            missing.append('debtor_name')
        elif not direction:
            missing.append('direction')
        return missing
    
    async def request_missing_info(self, update, context, debt_info, missing, processing_msg):
        questions = {
            'amount': "💰 Qancha pul? (masalan: 50000)",
            'creditor_name': "👤 Kim qarz berdi?",
            'debtor_name': "👤 Kimga qarz berdingiz?",
            'direction': "❓ Kim kimga qarz berdi?",
            'reason': "📝 Nima uchun?"
        }
        
        self.user_context[update.effective_user.id] = {
            'debt_info': debt_info,
            'missing': missing,
            'step': 0,
            'message_id': processing_msg.message_id
        }
        
        question_text = questions.get(missing[0], "Ma'lumot kerak")
        await processing_msg.edit_text(f"❓ {question_text}")
    
    async def create_debt_confirmation(self, update, context, debt_info, processing_msg):
        user = update.effective_user
        direction = debt_info.get('direction')
        
        if direction == 'owe_me':
            creditor_id = user.id
            creditor_name = user.first_name
            debtor_name = debt_info.get('creditor_name') or debt_info.get('debtor_name')
        else:
            debtor_id = user.id
            debtor_name = user.first_name
            creditor_name = debt_info.get('creditor_name') or debt_info.get('debtor_name')
        
        other_user = None
        debtor_username = None
        creditor_username = None
        if debtor_name and debtor_name.startswith('@'):
            other_user = self.db.find_user_by_username(debtor_name)
            debtor_username = debtor_name if not other_user else None
        elif creditor_name and creditor_name.startswith('@'):
            other_user = self.db.find_user_by_username(creditor_name)
            creditor_username = creditor_name if not other_user else None
        
        debt_id = f"pending_{user.id}_{int(datetime.now().timestamp())}"
        self.pending_debts[debt_id] = {
            'creator_id': user.id,
            'creditor_id': creditor_id if direction == 'owe_me' else (other_user['user_id'] if other_user else None),
            'debtor_id': debtor_id if direction == 'i_owe' else (other_user['user_id'] if other_user else None),
            'creditor_name': creditor_name,
            'debtor_name': debtor_name,
            'creditor_username': creditor_username,
            'debtor_username': debtor_username,
            'amount': debt_info['amount'],
            'currency': debt_info.get('currency', "so'm"),
            'reason': debt_info.get('reason', 'Sababsiz'),
            'direction': direction,
            'other_user': other_user
        }
        
        confirmation_text = ("✅ *Tasdiqlash kerak:*\n\n"
                           f"💰 Summa: {debt_info['amount']:,} so'm\n"
                           f"📝 Sabab: {debt_info.get('reason', 'Sababsiz')}\n"
                           f"👤 Qarz beruvchi: {creditor_name}\n"
                           f"👤 Qarz oluvchi: {debtor_name}\n\n")
        
        if not other_user:
            confirmation_text += "⚠️ Foydalanuvchi topilmadi. @username yoki kontakt ulashing.\n\n"
        
        confirmation_text += "Bu to'g'rimi?"
        
        keyboard = [[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{debt_id}"),
                    InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_{debt_id}")]]
        
        if not other_user:
            keyboard.append([InlineKeyboardButton("🔍 Username", callback_data=f"adduser_{debt_id}")])
        
        await processing_msg.edit_text(confirmation_text, parse_mode='Markdown', 
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_group_split(self, query, split_type):
        user_id = query.from_user.id
        user_ctx = self.user_context.get(user_id, {})
        debt_info = user_ctx.get('debt_info', {})
        processing_msg_id = user_ctx.get('processing_msg_id')
        
        if not debt_info:
            await query.answer("❌ Kontekst topilmadi.")
            return
        
        participants = debt_info.get('participants', [])
        payer_name = debt_info.get('payer_name', '')
        total_amount = debt_info.get('total_amount', 0)
        reason = debt_info.get('reason', 'Umumiy xarajat')
        
        # Assume "Men" means the current user
        if payer_name.lower() == 'men':
            payer_name = query.from_user.first_name
        
        # Filter out payer from participants
        debtors = [p for p in participants if p.lower() not in ['men', payer_name.lower()]]
        num_debtors = len(debtors)

        # Check if this matches an existing circle
        circle_id = self.db.find_circle_by_members(user_id, debtors)

        if not circle_id and not user_ctx.get('circle_asked'):
            # Ask for circle name
            self.user_context[user_id]['circle_asked'] = True
            self.user_context[user_id]['split_type'] = split_type
            
            keyboard = [
                [InlineKeyboardButton("👔 Hamkasblar", callback_data="circle_colleagues")],
                [InlineKeyboardButton("👫 Do'stlar", callback_data="circle_friends")],
                [InlineKeyboardButton("👨‍👩‍👧 Oila", callback_data="circle_family")],
                [InlineKeyboardButton("⏭️ O'tkazib yuborish", callback_data=f"skip_circle_{split_type}")]
            ]
            
            await query.edit_message_text(
                "👥 Bu kishilar qaysi guruhga tegishli?\n\n"
                "Keyingi safar avtomatik taniy olaman:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        if split_type == 'equal':
            # Calculate per person amount (including payer)
            num_people = len(participants)
            per_person = total_amount / num_people
            
            # Payer's share is already paid, others owe their share to payer
            group_debts = []
            for debtor in debtors:
                group_debts.append({
                    'direction': 'owe_me',
                    'creditor_name': payer_name,
                    'debtor_name': debtor,
                    'amount': per_person,
                    'currency': 'so\'m',
                    'reason': reason
                })
            
            # Store group debts for confirmation
            self.user_context[user_id] = {
                'action': 'confirm_group',
                'group_debts': group_debts,
                'processing_msg_id': processing_msg_id
            }
            
            confirmation_text = (
                f"✅ Teng bo'lish:\n\n"
                f"💰 Jami: {total_amount:,.0f} so'm\n"
                f"👥 Kishilar soni: {num_people}\n"
                f"💵 Har bir kishi: {per_person:,.0f} so'm\n\n"
                f"Siz {payer_name} sifatida {per_person:,.0f} so'm to'ladingiz (sizning ulushingiz).\n"
                f"Qolgan {len(debtors)} kishi har biri sizga {per_person:,.0f} so'm to'lashi kerak.\n\n"
                f"Tasdiqlaysizmi?"
            )
            keyboard = [
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_group")],
                [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_group")]
            ]
            await query.edit_message_text(confirmation_text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif split_type == 'unequal':
            # Calculate how much others should pay back (excluding payer's own share)
            num_people = len(participants)
            payer_share = total_amount / num_people
            amount_to_split = total_amount - payer_share  # Others pay back this amount
            
            self.user_context[user_id] = {
                'action': 'unequal_split',
                'debtors': debtors,
                'current_debtor_index': 0,
                'amounts': [0] * len(debtors),
                'total_amount': amount_to_split,  # Changed: split only what others owe
                'original_total': total_amount,
                'payer_share': payer_share,
                'payer_name': payer_name,
                'reason': reason,
                'processing_msg_id': processing_msg_id
            }
            
            await query.edit_message_text(
                f"📊 *Turli bo'lish:*\n\n"
                f"💰 Jami to'langan: {total_amount:,.0f} so'm\n"
                f"👥 Kishilar: {num_people} kishi\n"
                f"📌 Sizning ulushingiz: {payer_share:,.0f} so'm\n\n"
                f"Qolgan {len(debtors)} kishi sizga qaytarishi kerak: {amount_to_split:,.0f} so'm\n\n"
                f"❓ {debtors[0]} qancha qaytarishi kerak? (so'm)"
            )
    async def confirm_group_debts(self, query):
        """Collect usernames before creating group debts - auto-detect from circles"""
        user_id = query.from_user.id
        user_ctx = self.user_context.get(user_id, {})
        group_debts = user_ctx.get('group_debts', [])
        processing_msg_id = user_ctx.get('processing_msg_id')
        
        if not group_debts:
            await query.answer("❌ Ma'lumot topilmadi.")
            return
        
        # Get unique debtors
        debtors = list(set([debt['debtor_name'] for debt in group_debts]))
        
        # Try to auto-detect usernames from circles
        debtor_usernames = {}
        unknown_debtors = []
        
        for debtor in debtors:
            # Search in all circles
            circles = self.db.get_user_circles(user_id)
            found = False
            
            for circle in circles:
                members = self.db.get_circle_members(circle['id'])
                for member in members:
                    if member['member_name'].lower() == debtor.lower():
                        # Found in circle!
                        debtor_usernames[debtor] = {
                            'user_id': member['member_user_id'],
                            'username': member['member_username'] or member.get('db_username'),
                            'first_name': member['member_name']
                        }
                        found = True
                        break
                if found:
                    break
            
            if not found:
                unknown_debtors.append(debtor)
        
        # If all debtors are known, skip username collection
        if not unknown_debtors:
            # Update group debts with known info
            for debt in group_debts:
                debtor_name = debt['debtor_name']
                if debtor_name in debtor_usernames:
                    user_info = debtor_usernames[debtor_name]
                    debt['debtor_id'] = user_info['user_id']
                    debt['debtor_username'] = user_info['username']
            
            # Show final confirmation
            await self.show_final_group_confirmation(query, group_debts)
            return
        
        # Need to collect unknown debtors
        self.user_context[user_id] = {
            'action': 'collect_usernames',
            'group_debts': group_debts,
            'debtors': unknown_debtors,
            'debtor_usernames': debtor_usernames,  # Keep known ones
            'current_debtor_index': 0,
            'processing_msg_id': processing_msg_id
        }
        
        await query.edit_message_text(
            f"👤 {unknown_debtors[0]} uchun telegram username kiriting:\n\n"
            f"Masalan: @username\n\n"
            f"Yoki kontakt ulashing.\n\n"
            f"ℹ️ Qolgan {len(unknown_debtors)} kishi uchun so'rayapman."
        )
    
    async def final_confirm_group_debts(self, query):
        """Create individual debts after final confirmation"""
        user_id = query.from_user.id
        user_ctx = self.user_context.get(user_id, {})
        group_debts = user_ctx.get('group_debts', [])
        confirmation_text = "✅ *Yakuniy tasdiqlash:*\n\n"
        total = 0
        if not group_debts:
            await query.answer("❌ Ma'lumot topilmadi.")
            return
        
        created_count = 0
        for debt_info in group_debts:
            try:
                # Create debt in database
                debt_id = self.db.create_debt(
                    creator_id=user_id,
                    creditor_id=user_id,  # Creator is always creditor in group expenses
                    debtor_id=debt_info.get('debtor_id'),
                    amount=debt_info['amount'],
                    currency=debt_info.get('currency', "so'm"),
                    reason=debt_info['reason'],
                    creditor_username=None,
                    debtor_username=debt_info.get('debtor_username') if not debt_info.get('debtor_id') else None
                )
                
                # Auto-confirm creator side
                self.db.confirm_debt(debt_id, user_id)
                
                # Send notification to debtor if registered
                if debt_info.get('debtor_id'):
                    notification_text = (
                        "🔔 *Yangi umumiy xarajat qarzingiz*\n\n"
                        f"💰 Summa: {debt_info['amount']:,.0f} so'm\n"
                        f"📝 Sabab: {debt_info['reason']}\n"
                        f"👤 Qarz beruvchi: {query.from_user.first_name}\n\n"
                        "Iltimos, tasdiqlang:"
                    )
                    
                    keyboard = [[
                        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"accept_debt_{debt_id}"),
                        InlineKeyboardButton("❌ E'tiroz", callback_data=f"dispute_debt_{debt_id}")
                    ]]
                    
                    try:
                        await query.get_bot().send_message(
                            chat_id=debt_info['debtor_id'],
                            text=notification_text,
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        self.db.create_notification(debt_info['debtor_id'], debt_id, notification_text, 'group_debt_created')
                    except Exception as e:
                        logger.error(f"Notification error for debt {debt_id}: {e}")
                
                created_count += 1
                
            except Exception as e:
                logger.error(f"Error creating group debt: {e}")
        for debt in group_debts:
            username_display = debt.get('debtor_username', 'username yo\'q')
            if debt.get('debtor_id'):
                username_display = f"✅ {username_display}"
            else:
                username_display = f"⏳ {username_display}"
            
            confirmation_text += f"• {debt['debtor_name']} ({username_display}): {debt['amount']:,.0f} so'm\n"
            total += debt['amount']
        confirmation_text += f"\n💰 Jami: {total:,.0f} so'm\n"
        confirmation_text += f"📝 Sabab: {group_debts[0]['reason']}\n\n"
        confirmation_text += "Tasdiqlaysizmi?"
        
        keyboard = [
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data="final_confirm_group")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_group")]
        ]
        del self.user_context[user_id]
        self.user_context[query.from_user.id] = {
            'action': 'final_confirm_group',
            'group_debts': group_debts
        }
        
        await query.edit_message_text(
            confirmation_text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.edit_message_text(
            f"✅ *Guruh qarzlari yaratildi!*\n\n"
            f"📊 Yaratilgan qarzlar: {created_count}\n"
            f"🔔 Ro'yxatdan o'tgan a'zolarga xabarnomalar yuborildi.\n"
            f"⏳ Ro'yxatdan o'tmagan a'zolar botga kirganida xabarnoma olishadi.",
            parse_mode='Markdown'
        )
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        if data.startswith('circle_'):
            circle_name = data.replace('circle_', '')
            user_ctx = self.user_context.get(query.from_user.id, {})
            
            # Map callback to circle names
            circle_names = {
                'colleagues': 'Hamkasblar',
                'friends': 'Do\'stlar',
                'family': 'Oila'
            }
            
            circle_display_name = circle_names.get(circle_name, circle_name)
            
            # Create circle
            debt_info = user_ctx.get('debt_info', {})
            participants = debt_info.get('participants', [])
            payer_name = debt_info.get('payer_name', '')
            debtors = [p for p in participants if p.lower() not in ['men', payer_name.lower()]]
            
            circle_id = self.db.create_circle(query.from_user.id, circle_display_name)
            
            # Add members to circle
            for debtor in debtors:
                self.db.add_member_to_circle(circle_id, debtor)
            
            await query.answer(f"✅ '{circle_display_name}' guruh saqlandi!")
            
            # Continue with split
            split_type = user_ctx.get('split_type', 'equal')
            await self.handle_group_split(query, split_type)
            return
        if data.startswith('skip_circle_'):
            split_type = data.replace('skip_circle_', '')
            self.user_context[query.from_user.id]['circle_asked'] = True
            await self.handle_group_split(query, split_type)
            return
        if data.startswith('split_'):
            split_type = data.replace('split_', '')
            await self.handle_group_split(query, split_type)
            return
        if data.startswith('history_'):
            page = int(data.replace('history_', ''))
            # Pass the query as update
            class FakeUpdate:
                def __init__(self, callback_query):
                    self.callback_query = callback_query
                    self.effective_user = callback_query.from_user
            
            fake_update = FakeUpdate(query)
            await self.show_history(fake_update, context, page=page)
            return
        
        if data == 'confirm_group':
            await self.confirm_group_debts(query)
            return
        if data == 'final_confirm_group':
            await self.final_confirm_group_debts(query)
            return
        if data == 'cancel_group':
            del self.user_context[query.from_user.id]
            await query.edit_message_text("❌ Bekor qilindi.")
            return
        
        if data.startswith('confirm_'):
            await self.confirm_debt_callback(query, data)
        elif data.startswith('cancel_'):
            debt_id = data.replace('cancel_', '')
            if debt_id in self.pending_debts:
                del self.pending_debts[debt_id]
            await query.edit_message_text("❌ Qarz bekor qilindi.")
        elif data.startswith('accept_debt_'):
            await self.accept_debt_callback(query, data)
        elif data.startswith('dispute_debt_'):
            await self.dispute_debt_callback(query, data)
        elif data.startswith('pay_'):
            await self.initiate_payment(query, data)
        elif data.startswith('adduser_'):
            await self.adduser_callback(query, data)
        elif data.startswith('remind_'):
            await self.send_reminder_callback(query, data)
    
    async def confirm_debt_callback(self, query, data):
        debt_id = data.replace('confirm_', '')
        
        if debt_id not in self.pending_debts:
            await query.edit_message_text("❌ Qarz topilmadi.")
            return
        
        debt_data = self.pending_debts[debt_id]
        
        created_debt_id = self.db.create_debt(
            creator_id=debt_data['creator_id'],
            creditor_id=debt_data['creditor_id'],
            debtor_id=debt_data['debtor_id'],
            amount=debt_data['amount'],
            currency=debt_data['currency'],
            reason=debt_data['reason'],
            creditor_username=debt_data.get('creditor_username'),
            debtor_username=debt_data.get('debtor_username')
        )
        
        if debt_data['creator_id'] == debt_data['creditor_id']:
            self.db.confirm_debt(created_debt_id, debt_data['creator_id'])
        elif debt_data['creator_id'] == debt_data['debtor_id']:
            self.db.confirm_debt(created_debt_id, debt_data['creator_id'])
        
        other_user_id = (debt_data['debtor_id'] if debt_data['creator_id'] == debt_data['creditor_id'] 
                        else debt_data['creditor_id'])
        
        notification_sent = False
        if other_user_id is not None:
            notification_text = ("🔔 *Yangi qarz*\n\n"
                               f"💰 Summa: {debt_data['amount']:,} so'm\n"
                               f"📝 Sabab: {debt_data['reason']}\n\n"
                               "Iltimos, tasdiqlang:")
            
            keyboard = [[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"accept_debt_{created_debt_id}"),
                        InlineKeyboardButton("❌ E'tiroz", callback_data=f"dispute_debt_{created_debt_id}")]]
            
            try:
                await query.get_bot().send_message(
                    chat_id=other_user_id,
                    text=notification_text,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                self.db.create_notification(other_user_id, created_debt_id, notification_text, 'debt_created')
                notification_sent = True
            except Exception as e:
                logger.error(f"Notification error: {e}")
        
        if notification_sent:
            await query.edit_message_text(
                f"✅ Qarz yaratildi!\n\n"
                f"💰 {debt_data['amount']:,} so'm\n"
                f"📝 {debt_data['reason']}\n\n"
                "Xabarnoma yuborildi.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"✅ Qarz yaratildi!\n\n"
                f"💰 {debt_data['amount']:,} so'm\n"
                f"📝 {debt_data['reason']}\n\n"
                "⚠️ Xabarnoma yuborilmadi (foydalanuvchi ro'yxatdan o'tmagan).",
                parse_mode='Markdown'
            )
        
        del self.pending_debts[debt_id]
    async def adduser_callback(self, query, data):
        """Handle adding username for pending debt"""
        debt_id = data.replace('adduser_', '')
        
        if debt_id not in self.pending_debts:
            await query.edit_message_text("❌ Qarz topilmadi yoki muddati o'tgan.")
            return
        
        # Store the debt_id in user context
        self.user_context[query.from_user.id] = {
            'action': 'add_username',
            'debt_id': debt_id
        }
        
        await query.message.reply_text(
            "👤 Foydalanuvchi username kiriting:\n\n"
            "Masalan: @fayzkhanov\n\n"
            "Yoki kontakt ulashing."
        )
    async def accept_debt_callback(self, query, data):
        debt_id = int(data.replace('accept_debt_', ''))
        user_id = query.from_user.id
        
        if self.db.confirm_debt(debt_id, user_id):
            debt = self.db.get_debt(debt_id)
            
            if debt and debt['status'] == 'active':
                await query.edit_message_text(
                    f"✅ Qarz tasdiqlandi!\n\n"
                    f"💰 {debt['amount']:,} so'm\n"
                    f"📝 {debt['reason']}",
                    parse_mode='Markdown'
                )
                
                try:
                    await query.get_bot().send_message(
                        chat_id=debt['creator_id'],
                        text=f"✅ {debt['amount']:,} so'm qarzingiz tasdiqlandi!"
                    )
                except:
                    pass
            else:
                await query.edit_message_text("✅ Tasdiqingiz qayd qilindi.")
        else:
            await query.edit_message_text("❌ Xatolik.")
    
    async def dispute_debt_callback(self, query, data):
        debt_id = int(data.replace('dispute_debt_', ''))
        debt = self.db.get_debt(debt_id)
        
        if debt:
            self.db.cancel_debt(debt_id, debt['creator_id'])
            await query.edit_message_text("❌ Qarz bekor qilindi.")
            
            try:
                await query.get_bot().send_message(
                    chat_id=debt['creator_id'],
                    text=f"❌ {debt['amount']:,} so'm qarzga e'tiroz bildirildi."
                )
            except:
                pass
    async def show_my_debts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        debts = self.db.get_user_debts(user_id)
        
        if not debts:
            await update.message.reply_text("📊 Faol qarzlar yo'q.\n\nQarz yaratish uchun ovozli xabar yuboring!")
            return
        
        # Group by person
        person_totals = {}
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            
            if debt['debtor_id'] == user_id:
                # I owe this person
                person = debt['creditor_name']
                person_totals[person] = person_totals.get(person, 0) - balance  # Negative
            else:
                # This person owes me
                person = debt['debtor_name']
                person_totals[person] = person_totals.get(person, 0) + balance  # Positive
        
        message = "📊 *Mening qarzlarim (odam bo'yicha):*\n\n"
        
        total_owe = 0
        total_owed = 0
        
        for person, balance in sorted(person_totals.items()):
            if balance < 0:
                total_owe += abs(balance)
                message += f"🔴 {person}: Men qarzdorman {abs(balance):,} so'm\n"
            elif balance > 0:
                total_owed += balance
                message += f"🟢 {person}: Menga qarz {balance:,} so'm\n"
        
        message += f"\n━━━━━━━━━━━━━━━━\n"
        message += f"💰 *Jami:*\n"
        message += f"❌ Men to'lashim kerak: {total_owe:,} so'm\n"
        message += f"✅ Menga to'lashlari kerak: {total_owed:,} so'm\n"
        message += f"📊 Balans: {(total_owed - total_owe):+,} so'm"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_i_owe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        debts = self.db.get_debts_i_owe(user_id)
        
        if not debts:
            await update.message.reply_text("💰 To'lash uchun qarzlar yo'q! 🎉")
            return
        
        message = "💰 *Men qarzdorman:*\n\n"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🔴 *#{debt['id']}* {debt['creditor_name']}ga\n"
            message += f"   💵 {balance:,} so'm\n   📝 {debt['reason']}\n   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n💰 Jami: {total:,} so'm"
        
        keyboard = []
        for debt in debts[:5]:
            balance = self.db.get_debt_balance(debt['id'])
            if balance > 0:
                keyboard.append([InlineKeyboardButton(
                    f"💳 To'lash #{debt['id']} ({balance:,} so'm)", 
                    callback_data=f"pay_{debt['id']}"
                )])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def show_owed_to_me(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        debts = self.db.get_debts_owed_to_me(user_id)
        
        if not debts:
            await update.message.reply_text("💵 Sizga hech kim qarz emas.")
            return
        
        message = "💵 *Menga qarzlar:*\n\n"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🟢 *#{debt['id']}* {debt['debtor_name']}dan\n"
            message += f"   💵 {balance:,} so'm\n   📝 {debt['reason']}\n   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n💰 Jami: {total:,} so'm"
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        all_debts = self.db.get_user_debts(user_id)
        
        total_owe = 0
        total_owed = 0
        active_count = 0
        pending_count = 0
        paid_count = 0
        
        for debt in all_debts:
            balance = self.db.get_debt_balance(debt['id'])
            
            if debt['status'] == 'active':
                active_count += 1
                if debt['debtor_id'] == user_id:
                    total_owe += balance
                else:
                    total_owed += balance
            elif debt['status'] == 'pending':
                pending_count += 1
            elif debt['status'] == 'paid':
                paid_count += 1
        
        stats_text = ("📊 *Statistika:*\n\n"
                     f"📈 Faol qarzlar: {active_count}\n"
                     f"🕐 Kutilmoqda: {pending_count}\n"
                     f"✅ To'langan: {paid_count}\n\n"
                     "━━━━━━━━━━━━━━━━\n"
                     "💰 *Moliyaviy holat:*\n"
                     f"❌ Men qarzdorman: {total_owe:,} so'm\n"
                     f"✅ Menga qarz: {total_owed:,} so'm\n"
                     f"📊 Balans: {(total_owed - total_owe):+,} so'm")
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    async def show_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
        # Check if this is from a button callback
        if hasattr(update, 'callback_query') and update.callback_query:
            user_id = update.callback_query.from_user.id
            is_callback = True
        else:
            user_id = update.effective_user.id
            is_callback = False
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Pagination settings
        per_page = 10
        offset = (page - 1) * per_page
        
        # Get total count
        cursor.execute('''
            SELECT COUNT(*) as total
            FROM debts d
            WHERE d.creditor_id = ? OR d.debtor_id = ?
        ''', (user_id, user_id))
        
        total_count = cursor.fetchone()['total']
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        
        # Get paginated results
        cursor.execute('''
            SELECT d.*, c.first_name as creditor_name, b.first_name as debtor_name
            FROM debts d
            LEFT JOIN users c ON d.creditor_id = c.user_id
            LEFT JOIN users b ON d.debtor_id = b.user_id
            WHERE d.creditor_id = ? OR d.debtor_id = ?
            ORDER BY d.created_at DESC
            LIMIT ? OFFSET ?
        ''', (user_id, user_id, per_page, offset))
        
        debts = cursor.fetchall()
        conn.close()
        
        if not debts:
            if is_callback:
                await update.callback_query.message.reply_text("📜 Tarix bo'sh.")
            else:
                await update.message.reply_text("📜 Tarix bo'sh.")
            return
        
        message = f"📜 *Tarix (sahifa {page}/{total_pages}):*\n\n"
        status_emoji = {'pending': '🟡', 'active': '🔵', 'paid': '✅', 'cancelled': '❌'}
        
        for debt in debts:
            d = dict(debt)
            emoji = status_emoji.get(d['status'], '⚪')
            message += f"{emoji} *#{d['id']}* "
            
            if d['debtor_id'] == user_id:
                message += f"{d["creditor_name"] or d.get("creditor_username", "Noma\'lum")}ga qarzdor\n"
            else:
                message += f"{d["debtor_name"] or d.get("debtor_username", "Noma\'lum")}dan qarz\n"
            
            message += f"   💰 {d['amount']:,} so'm\n   📝 {d['reason']}\n"
            message += f"   📅 {d['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n"
        message += f"📄 Sahifa {page} / {total_pages}\n"
        message += f"📊 Jami: {total_count} ta yozuv"
        
        # Add pagination buttons
        keyboard = []
        nav_buttons = []
        
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"history_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"history_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        if is_callback:
            await update.callback_query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def send_reminder_callback(self, query, data):
        debt_id = int(data.replace('remind_', ''))
        debt = self.db.get_debt(debt_id)
        
        if not debt or debt['creditor_id'] != query.from_user.id:
            await query.edit_message_text("❌ Xatolik.")
            return
        
        if debt['debtor_id'] is None:
            await query.edit_message_text("❌ Eslatma yuborib bo'lmaydi (foydalanuvchi ro'yxatdan o'tmagan).")
            return
        
        balance = self.db.get_debt_balance(debt_id)
        
        if balance <= 0:
            await query.edit_message_text("✅ Qarz to'langan!")
            return
        
        reminder_text = (f"🔔 *Eslatma*\n\n"
                        f"Sizning {debt['creditor_name']}ga qarzingiz:\n"
                        f"💰 Summa: {balance:,} so'm\n"
                        f"📝 Sabab: {debt['reason']}\n"
                        f"📅 Yaratilgan: {debt['created_at'][:10]}\n\n"
                        "Iltimos, qarzni to'lashni unutmang!")
        
        try:
            await query.get_bot().send_message(chat_id=debt['debtor_id'], text=reminder_text, parse_mode='Markdown')
            await query.edit_message_text(f"✅ Eslatma yuborildi!\n\n📨 {debt['debtor_name']}ga")
            self.db.create_notification(debt['debtor_id'], debt_id, "Qarz eslatmasi", 'reminder')
        except Exception as e:
            logger.error(f"Reminder error: {e}")
            await query.edit_message_text("❌ Eslatma yuborilmadi.")
    
    async def initiate_payment(self, query, data):
        debt_id = int(data.replace('pay_', ''))
        debt = self.db.get_debt(debt_id)
        
        if not debt:
            await query.edit_message_text("❌ Qarz topilmadi.")
            return
        
        balance = self.db.get_debt_balance(debt_id)
        
        if balance <= 0:
            await query.edit_message_text("✅ Qarz to'langan!")
            return
        
        self.user_context[query.from_user.id] = {'action': 'payment', 'debt_id': debt_id, 'balance': balance}
        
        await query.message.reply_text(
            f"💳 *To'lov:*\n\n"
            f"Qarz: #{debt_id}\n"
            f"Qolgan: {balance:,} so'm\n\n"
            "Qancha to'lamoqchisiz?",
            parse_mode='Markdown'
        )
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        contact = update.message.contact
        user_id = update.effective_user.id
        
        self.db.create_user(contact.user_id, None, contact.first_name, contact.last_name)
        
        if user_id in self.user_context and 'debt_info' in self.user_context[user_id]:
            debt_ctx = self.user_context[user_id]
            debt_info = debt_ctx['debt_info']
            
            if debt_info.get('direction') == 'owe_me':
                debt_info['creditor_name'] = contact.first_name
            else:
                debt_info['debtor_name'] = contact.first_name
            
            debt_ctx['contact_user_id'] = contact.user_id
            await update.message.reply_text(f"✅ Kontakt qabul qilindi: {contact.first_name}")
        else:
            await update.message.reply_text(f"✅ Kontakt saqlandi: {contact.first_name}")
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        user_id = update.effective_user.id
        
        if text == "💰 Men qarzdorman":
            await self.show_i_owe(update, context)
        elif text == "💵 Menga qarzlar":
            await self.show_owed_to_me(update, context)
        elif text == "📜 Tarix":
            await self.show_history(update, context, page=1)
        elif text == "ℹ️ Yordam":
            await self.help_command(update, context)
        elif text == "📊 Statistika":
            await self.show_statistics(update, context)
        else:
            # Check if user is in a context
            if user_id in self.user_context:
                await self.handle_context_response(update, context)
            else:
                # Try to parse text as debt
                processing_msg = await update.message.reply_text("⏳ Tahlil qilyapman...")
                debt_info = await self.parse_debt_info(text, update.effective_user)
                
                if debt_info.get('error'):
                    await processing_msg.delete()
                    await update.message.reply_text(
                        "📱 Qarz yaratish uchun *ovozli xabar* yuboring.\n\n"
                        "Yoki quyidagi tugmalardan foydalaning:",
                        parse_mode='Markdown'
                    )
                    return
                
                # Handle parsed debt like voice message
                if debt_info.get('clarification_needed'):
                    self.user_context[user_id] = {
                        'action': 'clarification',
                        'original_text': text,
                        'processing_msg_id': processing_msg.message_id
                    }
                    await processing_msg.edit_text(debt_info['clarification_question'])
                    return
                
                if debt_info.get('is_group'):
                    self.user_context[user_id] = {
                        'action': 'split_type',
                        'debt_info': debt_info,
                        'processing_msg_id': processing_msg.message_id
                    }
                    keyboard = [
                        [InlineKeyboardButton("🟰 Teng bo'lish", callback_data="split_equal")],
                        [InlineKeyboardButton("📊 Turli bo'lish", callback_data="split_unequal")]
                    ]
                    await processing_msg.edit_text("❓ Umumiy xarajatlarni qanday bo'lish kerak?", reply_markup=InlineKeyboardMarkup(keyboard))
                    return
                
                missing = self.check_missing_info(debt_info)
                if missing:
                    await self.request_missing_info(update, context, debt_info, missing, processing_msg)
                    return
                
                await self.create_debt_confirmation(update, context, debt_info, processing_msg)
    
    async def handle_context_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        user_ctx = self.user_context[user_id]
        
        if user_ctx.get('action') == 'payment':
            try:
                amount = float(text.replace(',', '').replace(' ', ''))
                debt_id = user_ctx['debt_id']
                balance = user_ctx['balance']
                
                if amount <= 0:
                    await update.message.reply_text("❌ Summa 0 dan katta bo'lishi kerak.")
                    return
                
                if amount > balance:
                    await update.message.reply_text(f"❌ Summa qoldiqdan katta.\nQoldiq: {balance:,} so'm")
                    return
                
                payment_id = self.db.add_payment(debt_id, user_id, amount)
                debt = self.db.get_debt(debt_id)
                self.db.confirm_payment(payment_id)
                new_balance = self.db.get_debt_balance(debt_id)
                
                if new_balance == 0:
                    await update.message.reply_text(
                        f"✅ *To'lov qabul qilindi!*\n\n"
                        f"💵 To'langan: {amount:,} so'm\n"
                        "🎉 Qarz to'liq to'landi!",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        f"✅ *To'lov qabul qilindi!*\n\n"
                        f"💵 To'langan: {amount:,} so'm\n"
                        f"📊 Qoldiq: {new_balance:,} so'm",
                        parse_mode='Markdown'
                    )
                
                try:
                    await context.bot.send_message(
                        chat_id=debt['creditor_id'],
                        text=f"💰 {debt['debtor_name']} {amount:,} so'm to'ladi!\nQarz: #{debt_id}\nQoldiq: {new_balance:,} so'm"
                    )
                except:
                    pass
                
                del self.user_context[user_id]
                
            except ValueError:
                await update.message.reply_text("❌ Iltimos, to'g'ri raqam kiriting.")
        elif user_ctx.get('action') == 'collect_usernames':
            # Collecting usernames for group members
            debtors = user_ctx['debtors']
            current_index = user_ctx['current_debtor_index']
            username = text.strip()
            
            # Try to find user
            other_user = self.db.find_user_by_username(username)
            
            if other_user:
                user_ctx['debtor_usernames'][debtors[current_index]] = {
                    'user_id': other_user['user_id'],
                    'username': f"@{other_user['username']}",
                    'first_name': other_user['first_name']
                }
                confirmation_msg = f"✅ Topildi: {other_user['first_name']}"
            else:
                # Store username for future linking
                clean_username = username.lstrip('@')
                user_ctx['debtor_usernames'][debtors[current_index]] = {
                    'user_id': None,
                    'username': f"@{clean_username}",
                    'first_name': debtors[current_index]
                }
                confirmation_msg = f"✅ Username saqlandi: @{clean_username} (botga kirishi kutilmoqda)"
            
            await update.message.reply_text(confirmation_msg)
            
            # Move to next debtor or finish
            if current_index + 1 < len(debtors):
                user_ctx['current_debtor_index'] = current_index + 1
                await update.message.reply_text(
                    f"👤 {debtors[current_index + 1]} uchun telegram username yoki kontaktni ulashing:\n\n"
                    f"Masalan: @username"
                )
            else:
                # All usernames collected
                group_debts = user_ctx['group_debts']
                debtor_usernames = user_ctx['debtor_usernames']
                
                # Update group debts with ALL collected usernames
                for debt in group_debts:
                    debtor_name = debt['debtor_name']
                    if debtor_name in debtor_usernames:
                        user_info = debtor_usernames[debtor_name]
                        debt['debtor_id'] = user_info['user_id']
                        debt['debtor_username'] = user_info['username']
                
                # Use the helper function
                class FakeQuery:
                    def __init__(self, user_id, message):
                        self.from_user = type('obj', (object,), {'id': user_id})
                        self.message = message
                    
                    async def edit_message_text(self, *args, **kwargs):
                        await self.message.reply_text(*args, **kwargs)
                
                fake_query = FakeQuery(user_id, update.message)
                await self.show_final_group_confirmation(fake_query, group_debts)
                del self.user_context[user_id]
            
                # Show final confirmation
                confirmation_text = "✅ *Yakuniy tasdiqlash:*\n\n"
                total = 0
                for debt in group_debts:
                    username = debt.get("debtor_username", "username yo`q")
                    confirmation_text += (
                        f"• {debt['debtor_name']} "
                        f"({username}): "
                        f"{debt['amount']:,.0f} so`m\n"
                    )
                    # confirmation_text += f"• {debt["debtor_name"]} ({debt.get("debtor_username", "username yo\\'q")}): {debt["amount"]:,.0f} so'm\n"
                    total += debt['amount']
                
                confirmation_text += f"\n💰 Jami: {total:,.0f} so'm\n"
                confirmation_text += f"📝 Sabab: {group_debts[0]['reason']}\n\n"
                confirmation_text += "Tasdiqlaysizmi?"
                
                keyboard = [
                    [InlineKeyboardButton("✅ Tasdiqlash", callback_data="final_confirm_group")],
                    [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_group")]
                ]
                
                user_ctx['action'] = 'final_confirm_group'
                
                await update.message.reply_text(
                    confirmation_text,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        elif user_ctx.get('action') == 'clarification':
            # Re-parse with additional clarification
            original_text = user_ctx['original_text']
            combined_text = f"{original_text} {text}"  # Append clarification to original
            debt_info = await self.parse_debt_info(combined_text, update.effective_user)
            
            processing_msg = await context.bot.get_message(chat_id=update.message.chat_id, message_id=user_ctx['processing_msg_id'])
            
            if debt_info.get('clarification_needed'):
                await update.message.reply_text(debt_info['clarification_question'])
                return  # Ask again if still unclear
            
            if debt_info.get('error'):
                await processing_msg.edit_text(f"❌ {debt_info['error']}\n\nIltimos, qaytadan urinib ko'ring.")
                del self.user_context[user_id]
                return
            
            if debt_info.get('is_group'):
                self.user_context[user_id] = {
                    'action': 'split_type',
                    'debt_info': debt_info,
                    'processing_msg_id': processing_msg.message_id
                }
                keyboard = [
                    [InlineKeyboardButton("🟰 Teng bo'lish", callback_data="split_equal")],
                    [InlineKeyboardButton("📊 Turli bo'lish", callback_data="split_unequal")]
                ]
                await processing_msg.edit_text("❓ Umumiy xarajatlarni qanday bo'lish kerak?", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            missing = self.check_missing_info(debt_info)
            if missing:
                await self.request_missing_info(update, context, debt_info, missing, processing_msg)
            else:
                await self.create_debt_confirmation(update, context, debt_info, processing_msg)
            
            del self.user_context[user_id]
        elif user_ctx.get('action') == 'unequal_split':
            # Clean and parse amount - handle all formats
            amount_str = text.lower().strip()
            
            # Remove dots, commas, spaces
            amount_str = amount_str.replace('.', '').replace(',', '').replace(' ', '')
            
            try:
                # Handle "ming" or "min" (thousand)
                if 'ming' in amount_str or 'min' in amount_str:
                    amount_str = amount_str.replace('ming', '').replace('min', '')
                    amount = float(re.sub(r'[^\d]', '', amount_str)) * 1000
                else:
                    amount = float(re.sub(r'[^\d]', '', amount_str))
            except ValueError:
                await update.message.reply_text("❌ Raqam kiriting. Masalan: 60000 yoki 60 ming")
                return
            
            index = user_ctx['current_debtor_index']
            user_ctx['amounts'][index] = amount
            
            debtors = user_ctx['debtors']
            if index + 1 < len(debtors):
                user_ctx['current_debtor_index'] = index + 1
                await update.message.reply_text(f"❓ {debtors[index + 1]} uchun qancha? (so'm)")
            else:
                # All amounts collected, check total
                total_assigned = sum(user_ctx['amounts'])
                if abs(total_assigned - user_ctx['total_amount']) > 1:  # Allow 1 som difference for rounding
                    # Restart the process
                    user_ctx['current_debtor_index'] = 0
                    user_ctx['amounts'] = [0] * len(debtors)
                    
                    await update.message.reply_text(
                        f"❌ Jami {total_assigned:,.0f} so'm, lekin kerakli {user_ctx['total_amount']:,.0f} so'm.\n\n"
                        f"Qaytadan boshlaylik:\n\n"
                        f"❓ {debtors[0]} uchun qancha? (so'm)"
                    )
                    return
                
                # Create group debts
                group_debts = []
                payer_name = user_ctx['payer_name']
                reason = user_ctx['reason']
                for i, debtor in enumerate(debtors):
                    group_debts.append({
                        'direction': 'owe_me',
                        'creditor_name': payer_name,
                        'debtor_name': debtor,
                        'amount': user_ctx['amounts'][i],
                        'currency': 'so\'m',
                        'reason': reason
                    })
                
                self.user_context[user_id] = {
                    'action': 'confirm_group',
                    'group_debts': group_debts,
                    'processing_msg_id': user_ctx['processing_msg_id']
                }
                
                confirmation_text = "✅ Turli bo'lish:\n\n"
                for i, debtor in enumerate(debtors):
                    confirmation_text += f"• {debtor}: {user_ctx['amounts'][i]:,.0f} so'm\n"
                confirmation_text += f"\n💰 Jami: {total_assigned:,.0f} so'm\n\nTasdiqlaysizmi?"
                
                keyboard = [
                    [InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_group")],
                    [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_group")]
                ]
                await update.message.reply_text(confirmation_text, reply_markup=InlineKeyboardMarkup(keyboard))

        if user_ctx.get('action') == 'add_username':
            debt_id = user_ctx['debt_id']
            username = text.strip()
            
            if debt_id in self.pending_debts:
                # Find user by username
                other_user = self.db.find_user_by_username(username)
                
                if other_user:
                    debt_data = self.pending_debts[debt_id]
                    
                    # Update the debt with found user
                    if debt_data.get('direction') == 'owe_me':
                        debt_data['debtor_id'] = other_user['user_id']
                        debt_data['debtor_name'] = other_user['first_name']
                    else:
                        debt_data['creditor_id'] = other_user['user_id']
                        debt_data['creditor_name'] = other_user['first_name']
                    
                    debt_data['other_user'] = other_user
                    
                    await update.message.reply_text(
                        f"✅ Foydalanuvchi topildi: {other_user['first_name']}\n\n"
                        "Endi tasdiqlash tugmasini bosing."
                    )
                else:
                    debt_data = self.pending_debts[debt_id]
                    clean_username = username.lstrip('@')
                    if debt_data.get('direction') == 'owe_me':
                        debt_data['debtor_id'] = None
                        debt_data['debtor_username'] = f'@{clean_username}'
                        debt_data['debtor_name'] = clean_username.capitalize()
                    else:
                        debt_data['creditor_id'] = None
                        debt_data['creditor_username'] = f'@{clean_username}'
                        debt_data['creditor_name'] = clean_username.capitalize()
                    debt_data['other_user'] = None
                    await update.message.reply_text(
                        f"✅ Username saqlandi: @{clean_username}\n"
                        "Foydalanuvchi botga kirganda avto yangilanadi.\n"
                        "Endi tasdiqlang."
                    )
            
            del self.user_context[user_id]
            return
        elif 'debt_info' in user_ctx:
            debt_info = user_ctx['debt_info']
            missing = user_ctx['missing']
            step = user_ctx['step']
            
            field = missing[step]
            if field == 'amount':
                try:
                    amount_str = text.replace(',', '').replace(' ', '').lower()
                    if 'ming' in amount_str:
                        amount_str = amount_str.replace('ming', '000')
                    amount = float(re.sub(r'[^\d.]', '', amount_str))
                    debt_info['amount'] = amount
                except:
                    await update.message.reply_text("❌ Summani tushunmadim. Raqam kiriting (masalan: 50000)")
                    return
            elif field in ['creditor_name', 'debtor_name']:
                debt_info[field] = text
            elif field == 'reason':
                debt_info['reason'] = text
            
            if step + 1 < len(missing):
                user_ctx['step'] = step + 1
                next_field = missing[step + 1]
                questions = {
                    'amount': "💰 Qancha pul?",
                    'creditor_name': "👤 Kim qarz berdi?",
                    'debtor_name': "👤 Kimga qarz berdingiz?",
                    'reason': "📝 Nima uchun?"
                }
                await update.message.reply_text(questions[next_field])
            else:
                del self.user_context[user_id]
                processing_msg = await update.message.reply_text("⏳ Qayd qilyapman...")
                await self.create_debt_confirmation(update, context, debt_info, processing_msg)

def main():
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    
    application = Application.builder().token(TOKEN).build()
    bot = DebtBot()
    
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(MessageHandler(filters.VOICE, bot.handle_voice))
    application.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    application.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()