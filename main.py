#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot Production Ready - Full Version (Single File)
All features: User management, Shop, Deposits, Admin panel, Giftcodes, Broadcast, etc.
"""

import asyncio
import logging
import os
import sys
import re
import json
import hashlib
import random
import string
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    Message, CallbackQuery, FSInputFile, InputMediaPhoto, InputMediaDocument,
    BufferedInputFile, ChatMember, ChatPermissions
)
from aiogram.utils.formatting import Text, Bold, Italic, Code, Pre, Underline
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Float, Boolean, Text, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.pool import StaticPool

import pytz
from dotenv import load_dotenv

load_dotenv()

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8416942368/AAHXJHBmbK1QUVoMcRSHpOh4EzdOSZ_H3S0")
if not BOT_TOKEN:
    print("BOT_TOKEN not set in .env or hardcoded")
    sys.exit(1)

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "8416942368").split(",") if x.strip().isdigit()]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    uid = Column(String(50), nullable=True)          # custom UID
    joined_at = Column(DateTime, default=lambda: datetime.now(TZ))
    balance = Column(Float, default=0.0)
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(DateTime, nullable=True)
    is_blocked = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    total_orders = Column(Integer, default=0)        # derived from orders count
    orders = relationship("Order", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")

class Tool(Base):
    __tablename__ = "tools"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, default=0.0)
    version = Column(String(20), default="1.0")
    image_url = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    orders = relationship("Order", back_populates="tool")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    tool_id = Column(Integer, ForeignKey("tools.id"))
    order_date = Column(DateTime, default=lambda: datetime.now(TZ))
    amount = Column(Float)
    status = Column(String(20), default="pending")   # pending, completed, cancelled
    user = relationship("User", back_populates="orders")
    tool = relationship("Tool", back_populates="orders")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float)
    type = Column(String(20))                        # deposit, purchase, gift, refund
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(TZ))
    user = relationship("User", back_populates="transactions")

class PaymentQR(Base):
    __tablename__ = "payment_qr"
    id = Column(Integer, primary_key=True)
    bank_name = Column(String(100))
    account_number = Column(String(50))
    account_name = Column(String(100))
    qr_image = Column(String(200))                  # file_id or URL
    is_active = Column(Boolean, default=True)

class GiftCode(Base):
    __tablename__ = "giftcodes"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, index=True)
    value = Column(Float)
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    expiry_date = Column(DateTime)
    is_active = Column(Boolean, default=True)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    content = Column(Text)
    media_type = Column(String(20))                  # text, photo, video, document
    media_file_id = Column(String(200), nullable=True)
    sent_at = Column(DateTime, default=lambda: datetime.now(TZ))
    is_broadcast = Column(Boolean, default=False)

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text)

class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=True)
    action = Column(Text)
    timestamp = Column(DateTime, default=lambda: datetime.now(TZ))

# ==================== DB ENGINE ====================
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db() -> Session:
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

# ==================== HELPERS ====================
def get_user(db: Session, telegram_id: int) -> Optional[User]:
    return db.query(User).filter(User.telegram_id == telegram_id).first()

def get_or_create_user(db: Session, message: Message) -> User:
    user = get_user(db, message.from_user.id)
    if not user:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            joined_at=datetime.now(TZ),
            is_admin=message.from_user.id in ADMIN_IDS
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.username = message.from_user.username
        user.full_name = message.from_user.full_name
        db.commit()
    return user

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_blocked_user(db: Session, user_id: int) -> bool:
    user = get_user(db, user_id)
    return user.is_blocked if user else False

def format_balance(balance: float) -> str:
    return f"{balance:,.0f} VND"

def format_date(dt: datetime) -> str:
    if dt:
        return dt.strftime("%d/%m/%Y %H:%M")
    return "Chưa có"

def generate_uid(length=10) -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

def log_action(db: Session, user_id: int, action: str):
    log = Log(user_id=user_id, action=action, timestamp=datetime.now(TZ))
    db.add(log)
    db.commit()

def vip_expiry_days(days=30):
    return datetime.now(TZ) + timedelta(days=days)

def escape_markdown(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

def generate_deposit_content(user_id: int, amount: float) -> str:
    return f"NAP_{user_id}_{int(amount)}"

# ==================== KEYBOARDS ====================
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🏠 Trang chủ"), KeyboardButton(text="👤 Tài khoản")],
        [KeyboardButton(text="💰 Nạp tiền"), KeyboardButton(text="🛒 Mua Tool")],
        [KeyboardButton(text="📦 Tool của tôi"), KeyboardButton(text="🎁 Giftcode")],
        [KeyboardButton(text="📜 Lịch sử"), KeyboardButton(text="📢 Thông báo")],
        [KeyboardButton(text="⚙️ Cài đặt"), KeyboardButton(text="☎️ Liên hệ")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="👥 Quản lý User"), KeyboardButton(text="🛠 Quản lý Tool")],
        [KeyboardButton(text="💳 Quản lý QR"), KeyboardButton(text="🎁 Tạo Giftcode")],
        [KeyboardButton(text="📢 Broadcast"), KeyboardButton(text="⚙️ Cài đặt hệ thống")],
        [KeyboardButton(text="🔙 Về menu chính")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Hủy")]], resize_keyboard=True)

def tool_shop_keyboard(tools: List[Tool]) -> InlineKeyboardMarkup:
    kb = []
    for t in tools:
        kb.append([InlineKeyboardButton(text=f"{t.name} - {format_balance(t.price)}", callback_data=f"tool_{t.id}")])
    kb.append([InlineKeyboardButton(text="🔄 Làm mới", callback_data="refresh_shop")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def tool_detail_keyboard(tool_id: int, has_purchased: bool) -> InlineKeyboardMarkup:
    kb = []
    if not has_purchased:
        kb.append([InlineKeyboardButton(text="✅ Mua ngay", callback_data=f"buy_tool_{tool_id}")])
    else:
        kb.append([InlineKeyboardButton(text="📥 Sử dụng Tool", callback_data=f"use_tool_{tool_id}")])
    kb.append([InlineKeyboardButton(text="🔙 Quay lại shop", callback_data="back_shop")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def deposit_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="💰 10,000 VND", callback_data="dep_10000"),
         InlineKeyboardButton(text="💰 20,000 VND", callback_data="dep_20000")],
        [InlineKeyboardButton(text="💰 50,000 VND", callback_data="dep_50000"),
         InlineKeyboardButton(text="💰 100,000 VND", callback_data="dep_100000")],
        [InlineKeyboardButton(text="💰 200,000 VND", callback_data="dep_200000"),
         InlineKeyboardButton(text="💰 500,000 VND", callback_data="dep_500000")],
        [InlineKeyboardButton(text="🔙 Quay lại", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_user_actions(user_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🔒 Khóa", callback_data=f"admin_block_{user_id}"),
         InlineKeyboardButton(text="🔓 Mở khóa", callback_data=f"admin_unblock_{user_id}")],
        [InlineKeyboardButton(text="🔄 Reset UID", callback_data=f"admin_reset_uid_{user_id}"),
         InlineKeyboardButton(text="👑 Đổi quyền Admin", callback_data=f"admin_toggle_admin_{user_id}")],
        [InlineKeyboardButton(text="⏳ Gia hạn VIP (30 ngày)", callback_data=f"admin_vip_{user_id}")],
        [InlineKeyboardButton(text="❌ Xóa User", callback_data=f"admin_delete_{user_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_tool_actions(tool_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="✏️ Sửa", callback_data=f"edit_tool_{tool_id}"),
         InlineKeyboardButton(text="🗑 Xóa", callback_data=f"delete_tool_{tool_id}")],
        [InlineKeyboardButton(text="🔙 Quay lại", callback_data="admin_tools_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_qr_actions() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="➕ Thêm QR", callback_data="admin_add_qr")],
        [InlineKeyboardButton(text="🔄 Đổi QR", callback_data="admin_change_qr")],
        [InlineKeyboardButton(text="🏦 Đổi ngân hàng", callback_data="admin_change_bank")],
        [InlineKeyboardButton(text="🔢 Đổi số tài khoản", callback_data="admin_change_accnum")],
        [InlineKeyboardButton(text="📤 Upload ảnh QR", callback_data="admin_upload_qr")],
        [InlineKeyboardButton(text="🔁 Bật/Tắt QR", callback_data="admin_toggle_qr")],
        [InlineKeyboardButton(text="🔙 Quay lại", callback_data="admin_back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==================== FSM STATES ====================
class DepositState(StatesGroup):
    waiting_screenshot = State()

class AdminBroadcastState(StatesGroup):
    waiting_content = State()

class AdminAddToolState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_price = State()
    waiting_version = State()
    waiting_image = State()

class AdminEditToolState(StatesGroup):
    waiting_field = State()
    waiting_new_value = State()

class AdminCreateGiftcodeState(StatesGroup):
    waiting_value = State()
    waiting_max_uses = State()
    waiting_expiry = State()

class AdminQRUploadState(StatesGroup):
    waiting_image = State()

# ==================== BOT INIT ====================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Middleware: check block status
@dp.message()
async def check_blocked(message: Message, state: FSMContext):
    db = get_db()
    if is_blocked_user(db, message.from_user.id):
        db.close()
        await message.answer("🚫 Tài khoản của bạn đã bị khóa. Vui lòng liên hệ admin.")
        return
    db.close()
    # continue to handler

@dp.callback_query()
async def check_blocked_callback(callback: CallbackQuery, state: FSMContext):
    db = get_db()
    if is_blocked_user(db, callback.from_user.id):
        db.close()
        await callback.answer("🚫 Tài khoản bị khóa.", show_alert=True)
        return
    db.close()
    # continue

# ==================== HANDLERS ====================

# ---------- Start / Home ----------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db = get_db()
    user = get_or_create_user(db, message)
    db.close()
    welcome_text = (
        f"👋 Chào mừng {user.full_name}!\n"
        f"Chào mừng đến với *Bot SPIDEY*.\n"
        f"Sử dụng menu bên dưới để bắt đầu.\n\n"
        f"📌 *Lưu ý:* Nếu bạn là admin, hãy dùng lệnh /admin để vào panel quản trị."
    )
    await message.answer(welcome_text, parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bạn không có quyền truy cập.")
        return
    await message.answer("👑 *Panel Admin*\nChọn chức năng bên dưới.", parse_mode="MarkdownV2", reply_markup=admin_menu_keyboard())

@dp.message(F.text == "🏠 Trang chủ")
async def home_menu(message: Message, state: FSMContext):
    await state.clear()
    db = get_db()
    user = get_or_create_user(db, message)
    db.close()
    await message.answer(f"🏠 *Trang chủ*\nChào {user.full_name}!", parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

# ---------- Account ----------
@dp.message(F.text == "👤 Tài khoản")
async def account_info(message: Message):
    db = get_db()
    user = get_or_create_user(db, message)
    # Count completed orders
    order_count = db.query(Order).filter(Order.user_id == user.id, Order.status == "completed").count()
    user.total_orders = order_count
    db.commit()
    vip_status = "✅ Đã kích hoạt" if user.is_vip else "❌ Chưa"
    if user.is_vip and user.vip_expiry:
        vip_status += f"\n📅 Hết hạn: {format_date(user.vip_expiry)}"
    uid_display = user.uid if user.uid else "Chưa có"
    text = (
        f"👤 *Tài khoản của bạn*\n\n"
        f"🆔 Telegram ID: `{user.telegram_id}`\n"
        f"👤 Tên: {user.full_name}\n"
        f"📛 Username: @{user.username if user.username else 'N/A'}\n"
        f"🔑 UID: `{uid_display}`\n"
        f"💰 Số dư: {format_balance(user.balance)}\n"
        f"⭐ VIP: {vip_status}\n"
        f"📦 Tổng đơn hàng: {order_count}\n"
        f"📅 Ngày tham gia: {format_date(user.joined_at)}"
    )
    db.close()
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

# ---------- Deposit ----------
@dp.message(F.text == "💰 Nạp tiền")
async def deposit_menu(message: Message, state: FSMContext):
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    db.close()
    if not qr:
        await message.answer("❌ Hiện tại chưa có phương thức nạp tiền. Vui lòng liên hệ admin.")
        return
    text = (
        f"💳 *Nạp tiền vào tài khoản*\n\n"
        f"🏦 Ngân hàng: *{qr.bank_name}*\n"
        f"🔢 Số tài khoản: `{qr.account_number}`\n"
        f"👤 Chủ tài khoản: *{qr.account_name}*\n\n"
        f"Vui lòng chọn số tiền cần nạp bên dưới hoặc nhập số tiền tùy chỉnh (gửi lệnh `/deposit 100000`).\n"
        f"Sau khi chuyển khoản, hãy gửi ảnh biên lai để admin xác nhận."
    )
    if qr.qr_image:
        try:
            await message.answer_photo(photo=qr.qr_image, caption=text, parse_mode="MarkdownV2", reply_markup=deposit_keyboard())
        except:
            await message.answer(text, parse_mode="MarkdownV2", reply_markup=deposit_keyboard())
    else:
        await message.answer(text, parse_mode="MarkdownV2", reply_markup=deposit_keyboard())

@dp.message(Command("deposit"))
async def deposit_custom(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Vui lòng nhập số tiền. Ví dụ: `/deposit 50000`", parse_mode="MarkdownV2")
        return
    try:
        amount = int(args[1])
        if amount <= 0:
            await message.answer("❌ Số tiền phải lớn hơn 0.")
            return
        await state.set_state(DepositState.waiting_screenshot)
        await state.update_data(amount=amount)
        await message.answer(
            f"Bạn chọn nạp {format_balance(amount)}.\n"
            f"Nội dung chuyển khoản: `{generate_deposit_content(message.from_user.id, amount)}`\n"
            f"Vui lòng chuyển khoản đúng số tiền và gửi ảnh biên lai (screenshot) vào đây.",
            parse_mode="MarkdownV2",
            reply_markup=cancel_keyboard()
        )
    except:
        await message.answer("❌ Số tiền không hợp lệ.")

@dp.callback_query(F.data.startswith("dep_"))
async def deposit_amount(callback: CallbackQuery, state: FSMContext):
    amount = int(callback.data.split("_")[1])
    await state.set_state(DepositState.waiting_screenshot)
    await state.update_data(amount=amount)
    await callback.message.answer(
        f"Bạn chọn nạp {format_balance(amount)}.\n"
        f"Nội dung chuyển khoản: `{generate_deposit_content(callback.from_user.id, amount)}`\n"
        f"Vui lòng chuyển khoản đúng số tiền và gửi ảnh biên lai (screenshot) vào đây.",
        parse_mode="MarkdownV2",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()

@dp.message(DepositState.waiting_screenshot, F.photo)
async def deposit_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    if not amount:
        await message.answer("❌ Có lỗi, vui lòng thử lại.")
        await state.clear()
        return
    file_id = message.photo[-1].file_id
    caption = (
        f"📥 *Yêu cầu nạp tiền*\n"
        f"👤 User: {message.from_user.id}\n"
        f"💰 Số tiền: {format_balance(amount)}\n"
        f"🖼 Ảnh biên lai đính kèm."
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo=file_id,
                caption=caption,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Duyệt", callback_data=f"dep_approve_{message.from_user.id}_{amount}"),
                        InlineKeyboardButton(text="❌ Từ chối", callback_data=f"dep_reject_{message.from_user.id}_{amount}")
                    ]
                ])
            )
        except:
            pass
    await message.answer("✅ Đã gửi yêu cầu nạp tiền. Vui lòng chờ admin xác nhận.", reply_markup=main_menu_keyboard())
    await state.clear()

@dp.message(DepositState.waiting_screenshot)
async def deposit_not_photo(message: Message, state: FSMContext):
    await message.answer("❌ Vui lòng gửi ảnh (screenshot) biên lai chuyển khoản.")

# Admin approve/reject deposit
@dp.callback_query(F.data.startswith("dep_approve_"))
async def deposit_approve(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    amount = float(parts[3])
    db = get_db()
    user = get_user(db, user_id)
    if not user:
        await callback.answer("User không tồn tại")
        db.close()
        return
    user.balance += amount
    trans = Transaction(user_id=user.id, amount=amount, type="deposit", description="Nạp tiền qua QR")
    db.add(trans)
    db.commit()
    db.close()
    await callback.message.edit_text(f"✅ Đã duyệt nạp {format_balance(amount)} cho user {user_id}.")
    await callback.answer("Đã duyệt")
    try:
        await bot.send_message(
            user_id,
            f"✅ Giao dịch nạp {format_balance(amount)} đã được xác nhận.\nSố dư hiện tại: {format_balance(user.balance)}"
        )
    except:
        pass

@dp.callback_query(F.data.startswith("dep_reject_"))
async def deposit_reject(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    amount = float(parts[3])
    await callback.message.edit_text(f"❌ Đã từ chối nạp {format_balance(amount)} cho user {user_id}.")
    await callback.answer("Đã từ chối")
    try:
        await bot.send_message(user_id, f"❌ Giao dịch nạp {format_balance(amount)} bị từ chối. Vui lòng kiểm tra lại và thử lại.")
    except:
        pass

# ---------- Shop ----------
@dp.message(F.text == "🛒 Mua Tool")
async def shop_list(message: Message):
    db = get_db()
    tools = db.query(Tool).filter(Tool.is_active == True).all()
    db.close()
    if not tools:
        await message.answer("❌ Hiện tại chưa có tool nào.", reply_markup=main_menu_keyboard())
        return
    text = "🛒 *Danh sách Tool*\n\nChọn tool để xem chi tiết:"
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=tool_shop_keyboard(tools))

@dp.callback_query(F.data == "refresh_shop")
async def refresh_shop(callback: CallbackQuery):
    db = get_db()
    tools = db.query(Tool).filter(Tool.is_active == True).all()
    db.close()
    if not tools:
        await callback.message.edit_text("❌ Hiện tại chưa có tool nào.")
        return
    text = "🛒 *Danh sách Tool*\n\nChọn tool để xem chi tiết:"
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=tool_shop_keyboard(tools))
    await callback.answer()

@dp.callback_query(F.data.startswith("tool_"))
async def tool_detail(callback: CallbackQuery):
    tool_id = int(callback.data.split("_")[1])
    db = get_db()
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        await callback.answer("Tool không tồn tại", show_alert=True)
        db.close()
        return
    user = get_or_create_user(db, callback.message)
    order = db.query(Order).filter(Order.user_id == user.id, Order.tool_id == tool_id, Order.status == "completed").first()
    has_purchased = order is not None
    db.close()
    text = (
        f"🔧 *{tool.name}*\n"
        f"📝 Mô tả: {tool.description or 'Không có'}\n"
        f"💰 Giá: {format_balance(tool.price)}\n"
        f"📦 Version: {tool.version}\n"
    )
    if has_purchased:
        text += "\n✅ *Bạn đã sở hữu tool này.*"
    else:
        text += "\n❌ Bạn chưa sở hữu tool này."
    if tool.image_url:
        try:
            await callback.message.answer_photo(photo=tool.image_url, caption=text, parse_mode="MarkdownV2",
                                                reply_markup=tool_detail_keyboard(tool_id, has_purchased))
        except:
            await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=tool_detail_keyboard(tool_id, has_purchased))
    else:
        await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=tool_detail_keyboard(tool_id, has_purchased))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_tool_"))
async def buy_tool(callback: CallbackQuery):
    tool_id = int(callback.data.split("_")[2])
    db = get_db()
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        await callback.answer("Tool không tồn tại", show_alert=True)
        db.close()
        return
    user = get_or_create_user(db, callback.message)
    if user.balance < tool.price:
        await callback.answer("❌ Số dư không đủ. Vui lòng nạp thêm.", show_alert=True)
        db.close()
        return
    user.balance -= tool.price
    order = Order(user_id=user.id, tool_id=tool_id, amount=tool.price, status="completed")
    trans = Transaction(user_id=user.id, amount=-tool.price, type="purchase", description=f"Mua tool {tool.name}")
    db.add(order)
    db.add(trans)
    user.total_orders += 1
    db.commit()
    db.close()
    await callback.message.edit_text(
        f"✅ Bạn đã mua thành công tool *{tool.name}* với giá {format_balance(tool.price)}.\n"
        f"Số dư còn lại: {format_balance(user.balance)}",
        parse_mode="MarkdownV2"
    )
    await callback.answer("Mua thành công!")

@dp.callback_query(F.data.startswith("use_tool_"))
async def use_tool(callback: CallbackQuery):
    tool_id = int(callback.data.split("_")[2])
    db = get_db()
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        await callback.answer("Tool không tồn tại", show_alert=True)
        db.close()
        return
    # Gửi thông tin sử dụng
    await callback.message.answer(
        f"📥 Tool *{tool.name}* đã sẵn sàng.\n"
        f"Liên hệ admin để nhận hướng dẫn sử dụng.",
        parse_mode="MarkdownV2"
    )
    await callback.answer()

@dp.callback_query(F.data == "back_shop")
async def back_shop(callback: CallbackQuery):
    db = get_db()
    tools = db.query(Tool).filter(Tool.is_active == True).all()
    db.close()
    text = "🛒 *Danh sách Tool*\n\nChọn tool để xem chi tiết:"
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=tool_shop_keyboard(tools))
    await callback.answer()

# ---------- My Tools ----------
@dp.message(F.text == "📦 Tool của tôi")
async def my_tools(message: Message):
    db = get_db()
    user = get_or_create_user(db, message)
    orders = db.query(Order).filter(Order.user_id == user.id, Order.status == "completed").all()
    if not orders:
        await message.answer("❌ Bạn chưa mua tool nào.", reply_markup=main_menu_keyboard())
        db.close()
        return
    text = "📦 *Tool của bạn:*\n\n"
    for o in orders:
        tool = db.query(Tool).filter(Tool.id == o.tool_id).first()
        if tool:
            text += f"🔹 {tool.name} - Version {tool.version}\n"
    db.close()
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

# ---------- Giftcode ----------
@dp.message(F.text == "🎁 Giftcode")
async def giftcode_menu(message: Message):
    await message.answer(
        "🎁 *Giftcode*\n\nNhập mã giftcode để nhận thưởng.\n"
        "Ví dụ: `/gift ABC123`\n\n"
        "Mã giftcode có giới hạn lượt sử dụng và ngày hết hạn.",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("gift"))
async def redeem_giftcode(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Vui lòng nhập mã giftcode. Ví dụ: `/gift ABC123`", parse_mode="MarkdownV2")
        return
    code = args[1].strip().upper()
    db = get_db()
    gift = db.query(GiftCode).filter(GiftCode.code == code, GiftCode.is_active == True).first()
    if not gift:
        await message.answer("❌ Mã giftcode không hợp lệ hoặc đã hết hạn.")
        db.close()
        return
    if gift.expiry_date < datetime.now(TZ):
        await message.answer("❌ Mã giftcode đã hết hạn.")
        db.close()
        return
    if gift.used_count >= gift.max_uses:
        await message.answer("❌ Mã giftcode đã được sử dụng hết số lần cho phép.")
        db.close()
        return
    user = get_or_create_user(db, message)
    user.balance += gift.value
    gift.used_count += 1
    trans = Transaction(user_id=user.id, amount=gift.value, type="gift", description=f"Nhận giftcode {code}")
    db.add(trans)
    db.commit()
    db.close()
    await message.answer(
        f"✅ Chúc mừng! Bạn đã nhận được {format_balance(gift.value)} từ giftcode `{code}`.\n"
        f"Số dư hiện tại: {format_balance(user.balance)}",
        parse_mode="MarkdownV2"
    )

# ---------- History ----------
@dp.message(F.text == "📜 Lịch sử")
async def history(message: Message):
    db = get_db()
    user = get_or_create_user(db, message)
    transactions = db.query(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.created_at.desc()).limit(20).all()
    if not transactions:
        await message.answer("📜 Bạn chưa có lịch sử giao dịch.", reply_markup=main_menu_keyboard())
        db.close()
        return
    text = "📜 *Lịch sử giao dịch (20 gần nhất)*\n\n"
    for t in transactions:
        sign = "+" if t.amount > 0 else ""
        text += f"🕒 {format_date(t.created_at)}: {sign}{format_balance(t.amount)} - {t.type} - {t.description or ''}\n"
    db.close()
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

# ---------- Notifications ----------
@dp.message(F.text == "📢 Thông báo")
async def notifications(message: Message):
    db = get_db()
    notifs = db.query(Notification).order_by(Notification.sent_at.desc()).limit(10).all()
    if not notifs:
        await message.answer("📢 Chưa có thông báo nào.", reply_markup=main_menu_keyboard())
        db.close()
        return
    text = "📢 *Thông báo mới nhất*\n\n"
    for n in notifs:
        if n.media_type == "text":
            text += f"📝 {n.content}\n🕒 {format_date(n.sent_at)}\n\n"
        else:
            text += f"📎 {n.media_type} - {format_date(n.sent_at)}\n\n"
    db.close()
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

# ---------- Settings ----------
@dp.message(F.text == "⚙️ Cài đặt")
async def settings(message: Message):
    db = get_db()
    user = get_or_create_user(db, message)
    db.close()
    await message.answer(
        "⚙️ *Cài đặt*\n\n"
        "🔔 Nhận thông báo: Bật (mặc định)\n"
        "🌐 Ngôn ngữ: Tiếng Việt\n"
        "📱 Phiên bản bot: 1.0.0\n\n"
        "Để liên hệ admin: /contact",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard()
    )

# ---------- Contact ----------
@dp.message(F.text == "☎️ Liên hệ")
async def contact(message: Message):
    await message.answer(
        "☎️ *Liên hệ*\n\n"
        "📱 Telegram: @spideyabd\n"
        "📢 Kênh: @SPIDEYFREEFILES\n"
        "👨‍💻 Admin: liên hệ qua tin nhắn trực tiếp.",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("contact"))
async def contact_command(message: Message):
    await contact(message)

# ---------- Admin Panel ----------
@dp.message(F.text == "🔙 Về menu chính")
async def back_to_main(message: Message):
    await message.answer("🏠 Về trang chủ", reply_markup=main_menu_keyboard())

@dp.message(F.text == "👥 Quản lý User")
async def admin_manage_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "👥 *Quản lý User*\n\n"
        "Nhập ID Telegram của user để quản lý.\n"
        "Hoặc gửi lệnh `/list_users` để xem danh sách.\n"
        "Hoặc gửi `/search_user tên` để tìm kiếm.",
        parse_mode="MarkdownV2",
        reply_markup=admin_menu_keyboard()
    )

@dp.message(Command("list_users"))
async def list_users(message: Message):
    if not is_admin(message.from_user.id):
        return
    db = get_db()
    users = db.query(User).all()
    db.close()
    if not users:
        await message.answer("Chưa có user nào.")
        return
    text = "👥 *Danh sách user*\n\n"
    for u in users[:50]:
        text += f"🆔 {u.telegram_id} - {u.full_name} - {'VIP' if u.is_vip else 'Thường'} - {format_balance(u.balance)}\n"
    if len(users) > 50:
        text += "\n... hiển thị 50 user đầu tiên."
    await message.answer(text, parse_mode="MarkdownV2")

@dp.message(Command("search_user"))
async def search_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Vui lòng nhập tên cần tìm. Ví dụ: `/search_user John`", parse_mode="MarkdownV2")
        return
    query = args[1]
    db = get_db()
    users = db.query(User).filter(User.full_name.contains(query)).limit(20).all()
    db.close()
    if not users:
        await message.answer("❌ Không tìm thấy user nào.")
        return
    text = f"🔍 *Kết quả tìm kiếm cho '{query}':*\n\n"
    for u in users:
        text += f"🆔 {u.telegram_id} - {u.full_name} - {'VIP' if u.is_vip else 'Thường'}\n"
    await message.answer(text, parse_mode="MarkdownV2")

@dp.message(lambda m: m.text and m.text.isdigit() and is_admin(m.from_user.id))
async def admin_user_detail(message: Message):
    user_id = int(message.text)
    db = get_db()
    user = get_user(db, user_id)
    if not user:
        await message.answer("❌ User không tồn tại.")
        db.close()
        return
    order_count = db.query(Order).filter(Order.user_id == user.id, Order.status == "completed").count()
    text = (
        f"👤 *Thông tin user*\n"
        f"ID: `{user.telegram_id}`\n"
        f"Tên: {user.full_name}\n"
        f"Username: @{user.username or 'N/A'}\n"
        f"UID: {user.uid or 'N/A'}\n"
        f"Số dư: {format_balance(user.balance)}\n"
        f"VIP: {'✅' if user.is_vip else '❌'}\n"
        f"VIP hết hạn: {format_date(user.vip_expiry) if user.vip_expiry else 'N/A'}\n"
        f"Bị khóa: {'✅' if user.is_blocked else '❌'}\n"
        f"Admin: {'✅' if user.is_admin else '❌'}\n"
        f"Ngày tham gia: {format_date(user.joined_at)}\n"
        f"Tổng đơn hàng: {order_count}"
    )
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=admin_user_actions(user_id))
    db.close()

# Admin inline actions
@dp.callback_query(F.data.startswith("admin_block_"))
async def admin_block_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    user_id = int(callback.data.split("_")[2])
    db = get_db()
    user = get_user(db, user_id)
    if user:
        user.is_blocked = True
        db.commit()
        await callback.message.edit_text(f"✅ Đã khóa user {user_id}")
        log_action(db, callback.from_user.id, f"Block user {user_id}")
    db.close()
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_unblock_"))
async def admin_unblock_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    user_id = int(callback.data.split("_")[2])
    db = get_db()
    user = get_user(db, user_id)
    if user:
        user.is_blocked = False
        db.commit()
        await callback.message.edit_text(f"✅ Đã mở khóa user {user_id}")
        log_action(db, callback.from_user.id, f"Unblock user {user_id}")
    db.close()
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_reset_uid_"))
async def admin_reset_uid(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    user_id = int(callback.data.split("_")[3])
    db = get_db()
    user = get_user(db, user_id)
    if user:
        new_uid = generate_uid()
        user.uid = new_uid
        db.commit()
        await callback.message.edit_text(f"✅ Đã reset UID cho user {user_id} thành `{new_uid}`")
        log_action(db, callback.from_user.id, f"Reset UID user {user_id}")
    db.close()
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_toggle_admin_"))
async def admin_toggle_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    user_id = int(callback.data.split("_")[3])
    db = get_db()
    user = get_user(db, user_id)
    if user:
        user.is_admin = not user.is_admin
        db.commit()
        await callback.message.edit_text(f"✅ Đã thay đổi quyền admin cho user {user_id} (hiện tại: {'Admin' if user.is_admin else 'User'})")
        log_action(db, callback.from_user.id, f"Toggle admin user {user_id}")
    db.close()
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_vip_"))
async def admin_give_vip(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    user_id = int(callback.data.split("_")[2])
    db = get_db()
    user = get_user(db, user_id)
    if user:
        user.is_vip = True
        user.vip_expiry = vip_expiry_days(30)
        db.commit()
        await callback.message.edit_text(f"✅ Đã gia hạn VIP 30 ngày cho user {user_id}")
        log_action(db, callback.from_user.id, f"Give VIP to user {user_id}")
        try:
            await bot.send_message(user_id, "🎉 Chúc mừng! Bạn đã được cấp VIP 30 ngày.")
        except:
            pass
    db.close()
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    user_id = int(callback.data.split("_")[2])
    db = get_db()
    user = get_user(db, user_id)
    if user:
        db.delete(user)
        db.commit()
        await callback.message.edit_text(f"✅ Đã xóa user {user_id}")
        log_action(db, callback.from_user.id, f"Delete user {user_id}")
    db.close()
    await callback.answer()

# ---------- Admin: Manage Tools ----------
@dp.message(F.text == "🛠 Quản lý Tool")
async def admin_tools(message: Message):
    if not is_admin(message.from_user.id):
        return
    db = get_db()
    tools = db.query(Tool).all()
    db.close()
    if not tools:
        await message.answer("Chưa có tool nào.", reply_markup=admin_menu_keyboard())
        return
    text = "🛠 *Danh sách Tool*\n\n"
    for t in tools:
        text += f"🔹 {t.id} - {t.name} - {format_balance(t.price)} - {'Active' if t.is_active else 'Inactive'}\n"
    text += "\nDùng lệnh /addtool để thêm tool mới.\nHoặc bấm vào tool bên dưới để sửa/xóa."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{t.id} - {t.name}", callback_data=f"admin_tool_{t.id}") for t in tools[:5]]
    ])
    if len(tools) > 5:
        kb.inline_keyboard.append([InlineKeyboardButton(text="🔄 Xem thêm", callback_data="admin_tools_page_2")])
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)

@dp.callback_query(F.data.startswith("admin_tool_"))
async def admin_tool_detail(callback: CallbackQuery):
    tool_id = int(callback.data.split("_")[2])
    db = get_db()
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    db.close()
    if not tool:
        await callback.answer("Tool không tồn tại")
        return
    text = (
        f"🔧 *{tool.name}*\n"
        f"ID: {tool.id}\n"
        f"📝 Mô tả: {tool.description or 'N/A'}\n"
        f"💰 Giá: {format_balance(tool.price)}\n"
        f"📦 Version: {tool.version}\n"
        f"🖼 Ảnh: {tool.image_url or 'N/A'}\n"
        f"Trạng thái: {'Hoạt động' if tool.is_active else 'Tạm dừng'}"
    )
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=admin_tool_actions(tool_id))
    await callback.answer()

@dp.callback_query(F.data == "admin_tools_page_2")
async def admin_tools_page2(callback: CallbackQuery):
    db = get_db()
    tools = db.query(Tool).all()
    db.close()
    text = "🛠 *Danh sách Tool (trang 2)*\n\n"
    for t in tools[5:10]:
        text += f"🔹 {t.id} - {t.name} - {format_balance(t.price)}\n"
    if len(tools) <= 10:
        text += "\nHết."
    await callback.message.edit_text(text, parse_mode="MarkdownV2")
    await callback.answer()

@dp.message(Command("addtool"))
async def admin_add_tool(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminAddToolState.waiting_name)
    await message.answer("Nhập tên tool:", reply_markup=cancel_keyboard())

@dp.message(AdminAddToolState.waiting_name, F.text)
async def add_tool_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminAddToolState.waiting_description)
    await message.answer("Nhập mô tả tool:")

@dp.message(AdminAddToolState.waiting_description, F.text)
async def add_tool_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AdminAddToolState.waiting_price)
    await message.answer("Nhập giá tool (số):")

@dp.message(AdminAddToolState.waiting_price, F.text)
async def add_tool_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        await state.update_data(price=price)
        await state.set_state(AdminAddToolState.waiting_version)
        await message.answer("Nhập version (ví dụ: 1.0):")
    except:
        await message.answer("❌ Vui lòng nhập số hợp lệ.")

@dp.message(AdminAddToolState.waiting_version, F.text)
async def add_tool_version(message: Message, state: FSMContext):
    await state.update_data(version=message.text)
    await state.set_state(AdminAddToolState.waiting_image)
    await message.answer("Gửi ảnh đại diện cho tool (có thể bỏ qua bằng cách gửi 'skip'):")

@dp.message(AdminAddToolState.waiting_image)
async def add_tool_image(message: Message, state: FSMContext):
    data = await state.get_data()
    image_url = None
    if message.text and message.text.lower() == "skip":
        image_url = None
    elif message.photo:
        image_url = message.photo[-1].file_id
    else:
        await message.answer("❌ Vui lòng gửi ảnh hoặc gửi 'skip' để bỏ qua.")
        return
    db = get_db()
    tool = Tool(
        name=data['name'],
        description=data['description'],
        price=data['price'],
        version=data['version'],
        image_url=image_url,
        is_active=True
    )
    db.add(tool)
    db.commit()
    db.close()
    await message.answer(f"✅ Đã thêm tool *{data['name']}* thành công.", parse_mode="MarkdownV2", reply_markup=admin_menu_keyboard())
    await state.clear()

@dp.message(AdminAddToolState.waiting_image, F.text == "❌ Hủy")
async def add_tool_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Đã hủy.", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data.startswith("edit_tool_"))
async def admin_edit_tool(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    tool_id = int(callback.data.split("_")[2])
    await state.update_data(edit_tool_id=tool_id)
    await state.set_state(AdminEditToolState.waiting_field)
    await callback.message.answer(
        "Nhập trường cần sửa (name, description, price, version, image, active):",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()

@dp.message(AdminEditToolState.waiting_field, F.text)
async def edit_tool_field(message: Message, state: FSMContext):
    field = message.text.lower()
    valid_fields = ["name", "description", "price", "version", "image", "active"]
    if field not in valid_fields:
        await message.answer("❌ Trường không hợp lệ. Các trường: " + ", ".join(valid_fields))
        return
    await state.update_data(edit_field=field)
    await state.set_state(AdminEditToolState.waiting_new_value)
    await message.answer(f"Nhập giá trị mới cho '{field}':")

@dp.message(AdminEditToolState.waiting_new_value, F.text)
async def edit_tool_new_value(message: Message, state: FSMContext):
    data = await state.get_data()
    tool_id = data['edit_tool_id']
    field = data['edit_field']
    new_value = message.text
    db = get_db()
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        await message.answer("❌ Tool không tồn tại.")
        db.close()
        await state.clear()
        return
    if field == "name":
        tool.name = new_value
    elif field == "description":
        tool.description = new_value
    elif field == "price":
        try:
            tool.price = float(new_value)
        except:
            await message.answer("❌ Giá phải là số.")
            db.close()
            return
    elif field == "version":
        tool.version = new_value
    elif field == "image":
        tool.image_url = new_value
    elif field == "active":
        tool.is_active = new_value.lower() in ["true", "1", "active", "on"]
    db.commit()
    db.close()
    await message.answer(f"✅ Đã cập nhật {field} thành '{new_value}'", reply_markup=admin_menu_keyboard())
    await state.clear()

@dp.callback_query(F.data.startswith("delete_tool_"))
async def admin_delete_tool(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    tool_id = int(callback.data.split("_")[2])
    db = get_db()
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if tool:
        db.delete(tool)
        db.commit()
        await callback.message.edit_text(f"✅ Đã xóa tool ID {tool_id}")
        log_action(db, callback.from_user.id, f"Delete tool {tool_id}")
    db.close()
    await callback.answer()

@dp.callback_query(F.data == "admin_tools_list")
async def admin_tools_list(callback: CallbackQuery):
    await admin_tools(callback.message)
    await callback.answer()

# ---------- Admin: QR Management ----------
@dp.message(F.text == "💳 Quản lý QR")
async def admin_qr_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    db.close()
    if qr:
        text = (
            f"💳 *QR hiện tại*\n"
            f"🏦 Ngân hàng: {qr.bank_name}\n"
            f"🔢 Số TK: {qr.account_number}\n"
            f"👤 Chủ TK: {qr.account_name}\n"
            f"🖼 Ảnh: {qr.qr_image or 'Không có'}\n"
            f"Trạng thái: {'✅ Hoạt động' if qr.is_active else '❌ Tạm dừng'}"
        )
    else:
        text = "Chưa có QR nào."
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=admin_qr_actions())

@dp.callback_query(F.data == "admin_add_qr")
async def admin_add_qr(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Không có quyền")
        return
    await state.set_state(AdminQRUploadState.waiting_image)
    await callback.message.answer("Vui lòng gửi ảnh QR mới (hoặc file_id).")
    await callback.answer()

@dp.message(AdminQRUploadState.waiting_image, F.photo)
async def admin_qr_upload_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(qr_image=file_id)
    await message.answer("Nhập tên ngân hàng:")
    await state.set_state("admin_qr_bank")

@dp.message(StateFilter("admin_qr_bank"), F.text)
async def admin_qr_bank(message: Message, state: FSMContext):
    await state.update_data(bank_name=message.text)
    await message.answer("Nhập số tài khoản:")
    await state.set_state("admin_qr_accnum")

@dp.message(StateFilter("admin_qr_accnum"), F.text)
async def admin_qr_accnum(message: Message, state: FSMContext):
    await state.update_data(account_number=message.text)
    await message.answer("Nhập tên chủ tài khoản:")
    await state.set_state("admin_qr_accname")

@dp.message(StateFilter("admin_qr_accname"), F.text)
async def admin_qr_accname(message: Message, state: FSMContext):
    data = await state.get_data()
    db = get_db()
    db.query(PaymentQR).update({PaymentQR.is_active: False})
    qr = PaymentQR(
        bank_name=data['bank_name'],
        account_number=data['account_number'],
        account_name=message.text,
        qr_image=data.get('qr_image'),
        is_active=True
    )
    db.add(qr)
    db.commit()
    db.close()
    await message.answer("✅ Đã thêm QR mới thành công.", reply_markup=admin_menu_keyboard())
    await state.clear()

@dp.callback_query(F.data == "admin_change_qr")
async def admin_change_qr(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminQRUploadState.waiting_image)
    await callback.message.answer("Gửi ảnh QR mới để thay thế (hoặc file_id).")
    await callback.answer()

@dp.message(AdminQRUploadState.waiting_image, F.photo)
async def admin_change_qr_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    if qr:
        qr.qr_image = file_id
        db.commit()
        await message.answer("✅ Đã đổi ảnh QR.")
    else:
        await message.answer("❌ Không có QR active. Vui lòng thêm QR mới.")
    db.close()
    await state.clear()
    await message.answer("Quay lại menu QR", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "admin_change_bank")
async def admin_change_bank(callback: CallbackQuery, state: FSMContext):
    await state.set_state("admin_change_bank_state")
    await callback.message.answer("Nhập tên ngân hàng mới:")
    await callback.answer()

@dp.message(StateFilter("admin_change_bank_state"), F.text)
async def admin_change_bank_value(message: Message, state: FSMContext):
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    if qr:
        qr.bank_name = message.text
        db.commit()
        await message.answer(f"✅ Đã đổi ngân hàng thành '{message.text}'")
    else:
        await message.answer("❌ Không có QR active.")
    db.close()
    await state.clear()
    await message.answer("Quay lại menu QR", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "admin_change_accnum")
async def admin_change_accnum(callback: CallbackQuery, state: FSMContext):
    await state.set_state("admin_change_accnum_state")
    await callback.message.answer("Nhập số tài khoản mới:")
    await callback.answer()

@dp.message(StateFilter("admin_change_accnum_state"), F.text)
async def admin_change_accnum_value(message: Message, state: FSMContext):
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    if qr:
        qr.account_number = message.text
        db.commit()
        await message.answer(f"✅ Đã đổi số tài khoản thành '{message.text}'")
    else:
        await message.answer("❌ Không có QR active.")
    db.close()
    await state.clear()
    await message.answer("Quay lại menu QR", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "admin_upload_qr")
async def admin_upload_qr(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminQRUploadState.waiting_image)
    await callback.message.answer("Vui lòng gửi ảnh QR mới (có thể là file_id hoặc ảnh).")
    await callback.answer()

@dp.message(AdminQRUploadState.waiting_image, F.photo)
async def admin_upload_qr_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    if qr:
        qr.qr_image = file_id
        db.commit()
        await message.answer("✅ Đã cập nhật ảnh QR.")
    else:
        await message.answer("❌ Không có QR active. Vui lòng thêm QR mới.")
    db.close()
    await state.clear()
    await message.answer("Quay lại menu QR", reply_markup=admin_menu_keyboard())

@dp.callback_query(F.data == "admin_toggle_qr")
async def admin_toggle_qr(callback: CallbackQuery):
    db = get_db()
    qr = db.query(PaymentQR).filter(PaymentQR.is_active == True).first()
    if qr:
        qr.is_active = False
        db.commit()
        await callback.message.answer("❌ Đã tắt QR hiện tại.")
    else:
        qr = db.query(PaymentQR).first()
        if qr:
            qr.is_active = True
            db.commit()
            await callback.message.answer("✅ Đã bật QR.")
        else:
            await callback.message.answer("❌ Không có QR nào để bật.")
    db.close()
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await callback.message.answer("Quay lại menu admin", reply_markup=admin_menu_keyboard())
    await callback.answer()

# ---------- Admin: Giftcode ----------
@dp.message(F.text == "🎁 Tạo Giftcode")
async def admin_create_giftcode(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminCreateGiftcodeState.waiting_value)
    await message.answer("Nhập giá trị giftcode (số tiền):", reply_markup=cancel_keyboard())

@dp.message(AdminCreateGiftcodeState.waiting_value, F.text)
async def admin_gift_value(message: Message, state: FSMContext):
    try:
        value = float(message.text)
        await state.update_data(value=value)
        await state.set_state(AdminCreateGiftcodeState.waiting_max_uses)
        await message.answer("Nhập số lần sử dụng tối đa (ví dụ: 1, 5, 10):")
    except:
        await message.answer("❌ Vui lòng nhập số hợp lệ.")

@dp.message(AdminCreateGiftcodeState.waiting_max_uses, F.text)
async def admin_gift_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text)
        await state.update_data(max_uses=max_uses)
        await state.set_state(AdminCreateGiftcodeState.waiting_expiry)
        await message.answer("Nhập ngày hết hạn (theo định dạng DD/MM/YYYY) hoặc 'never' để không hết hạn:")
    except:
        await message.answer("❌ Vui lòng nhập số nguyên.")

@dp.message(AdminCreateGiftcodeState.waiting_expiry, F.text)
async def admin_gift_expiry(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == "never":
        expiry = datetime.now(TZ) + timedelta(days=365*10)
    else:
        try:
            expiry = datetime.strptime(message.text, "%d/%m/%Y")
            expiry = TZ.localize(expiry)
        except:
            await message.answer("❌ Định dạng ngày không hợp lệ. Vui lòng dùng DD/MM/YYYY hoặc 'never'.")
            return
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    db = get_db()
    gift = GiftCode(
        code=code,
        value=data['value'],
        max_uses=data['max_uses'],
        expiry_date=expiry,
        is_active=True
    )
    db.add(gift)
    db.commit()
    db.close()
    await message.answer(
        f"✅ Giftcode đã tạo thành công!\n"
        f"Mã: `{code}`\n"
        f"Giá trị: {format_balance(data['value'])}\n"
        f"Số lần sử dụng: {data['max_uses']}\n"
        f"Hết hạn: {format_date(expiry)}",
        parse_mode="MarkdownV2",
        reply_markup=admin_menu_keyboard()
    )
    await state.clear()

@dp.message(Command("list_giftcodes"))
async def list_giftcodes(message: Message):
    if not is_admin(message.from_user.id):
        return
    db = get_db()
    gifts = db.query(GiftCode).all()
    db.close()
    if not gifts:
        await message.answer("Chưa có giftcode nào.")
        return
    text = "🎁 *Danh sách Giftcode*\n\n"
    for g in gifts:
        status = "✅ Hoạt động" if g.is_active and g.expiry_date > datetime.now(TZ) and g.used_count < g.max_uses else "❌ Hết hạn/dùng"
        text += f"`{g.code}` - {format_balance(g.value)} - {g.used_count}/{g.max_uses} - Hết hạn: {format_date(g.expiry_date)} - {status}\n"
    await message.answer(text, parse_mode="MarkdownV2")

# ---------- Admin: Broadcast ----------
@dp.message(F.text == "📢 Broadcast")
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminBroadcastState.waiting_content)
    await message.answer(
        "Nhập nội dung thông báo (có thể kèm media):\n"
        "Bạn có thể gửi tin nhắn dạng text, ảnh, video, file.\n"
        "Sau khi gửi, bot sẽ hỏi lại xác nhận.",
        reply_markup=cancel_keyboard()
    )

@dp.message(AdminBroadcastState.waiting_content)
async def admin_broadcast_content(message: Message, state: FSMContext):
    media_type = "text"
    media_file_id = None
    content = message.text
    if message.photo:
        media_type = "photo"
        media_file_id = message.photo[-1].file_id
        content = message.caption or ""
    elif message.video:
        media_type = "video"
        media_file_id = message.video.file_id
        content = message.caption or ""
    elif message.document:
        media_type = "document"
        media_file_id = message.document.file_id
        content = message.caption or ""
    await state.update_data(media_type=media_type, media_file_id=media_file_id, content=content)
    preview_text = f"📢 *Nội dung broadcast:*\n\n{content}\n\nLoại: {media_type}"
    await message.answer(preview_text, parse_mode="MarkdownV2")
    await message.answer(
        "Gửi /confirm_broadcast để gửi thông báo này cho tất cả user.\n"
        "Hoặc /cancel để hủy."
    )

@dp.message(Command("confirm_broadcast"))
async def confirm_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    if not data:
        await message.answer("❌ Không có dữ liệu broadcast.")
        return
    db = get_db()
    users = db.query(User).all()
    total = len(users)
    success = 0
    for user in users:
        try:
            if data['media_type'] == "text":
                await bot.send_message(user.telegram_id, data['content'], parse_mode="MarkdownV2")
            elif data['media_type'] == "photo":
                await bot.send_photo(user.telegram_id, data['media_file_id'], caption=data['content'], parse_mode="MarkdownV2")
            elif data['media_type'] == "video":
                await bot.send_video(user.telegram_id, data['media_file_id'], caption=data['content'], parse_mode="MarkdownV2")
            elif data['media_type'] == "document":
                await bot.send_document(user.telegram_id, data['media_file_id'], caption=data['content'], parse_mode="MarkdownV2")
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    notif = Notification(
        content=data['content'],
        media_type=data['media_type'],
        media_file_id=data['media_file_id'],
        is_broadcast=True,
        sent_at=datetime.now(TZ)
    )
    db.add(notif)
    db.commit()
    db.close()
    await message.answer(f"✅ Broadcast đã gửi thành công tới {success}/{total} user.")
    await state.clear()
    await message.answer("Quay lại menu admin", reply_markup=admin_menu_keyboard())

@dp.message(Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Đã hủy broadcast.", reply_markup=admin_menu_keyboard())

# ---------- Fallback ----------
@dp.message()
async def fallback(message: Message):
    await message.answer("❌ Vui lòng sử dụng menu hoặc lệnh hợp lệ.", reply_markup=main_menu_keyboard())

# ==================== MAIN ====================
async def on_startup():
    logger.info("Bot is starting...")

async def main():
    await on_startup()
    logger.info("Bot polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())