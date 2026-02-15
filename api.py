# -*- coding: utf-8 -*-
import asyncio
import os
import re
import json
import sys
import time
import unicodedata
import threading
from telethon import TelegramClient
from telethon.sessions import StringSession
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# Force UTF-8
try:
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)
except Exception:
    pass

# ========== CONFIG ==========
API_ID = os.environ.get('API_ID', '17570480')
API_HASH = os.environ.get('API_HASH', '18c5be05094b146ef29b0cb6f6601f1f')
SESSION_STRING = os.environ.get('SESSION_STRING', "1ApWapzMBu0NYE8mBCNSqckiBtat2n26StfHX1k4VFOL9G547ShPWlgR1N6ysqX0JiTAMrpAtCzmpewdQab8RoYIU-6v6FV0j0NU3xtRdMUyvbpD5CkS3U_pKO08JWmzThQSIHkYG3gcIK8NvyCR1S9BzmUgsIxYcDU8sXVXnjD_E2CCSLVSY56rdleZYrYMScAeiSqnup-5IL1BPepP2eX8VcCvWyzFEn8C4tvbkIRGSpEEnlBwfsSE68LbR5HA0KAYRZwUekIPi0xy83CbQADQnlmIq0b-wZL91BRJ7heiMgifJHew_uk4d42Fa3wvigWn9_Q5kcc1dXcYJ4t4x0cY36RkKSB8=")
BOT_USERNAME = os.environ.get('BOT_USERNAME', "Miyavrem_bot")

# Render için port binding
PORT = int(os.environ.get('PORT', 5000))

# ========== GLOBALS ==========
client = None
client_lock = threading.Lock()
loop = None
result_cache = {}
app_started = False

# ========== IMPROVED UTILITIES ==========

def fix_unicode_escapes(text: str) -> str:
    """Unicode escape karakterlerini (\u0130, \u00e7 vb.) düzgün Türkçe karakterlere çevir"""
    if not text:
        return ""
    
    try:
        if '\\u' in text:
            text = text.replace('\\\\u', '\\u')
            decoded = bytes(text, 'utf-8').decode('unicode_escape')
            return decoded
    except Exception as e:
        print(f"Unicode escape fix error: {e}")
    
    return text


def normalize_turkish_text(text: str) -> str:
    """Türkçe metni normalize et"""
    if not text:
        return ""
    
    text = fix_unicode_escapes(text)
    
    try:
        text = unicodedata.normalize('NFKC', text)
    except:
        pass
    
    turkish_mapping = {
        '\u0130': 'İ', '\u0131': 'ı', '\u011f': 'ğ', '\u011e': 'Ğ',
        '\u015f': 'ş', '\u015e': 'Ş', '\u00e7': 'ç', '\u00c7': 'Ç',
        '\u00fc': 'ü', '\u00dc': 'Ü', '\u00f6': 'ö', '\u00d6': 'Ö',
        '\u00e4': 'ä', '\u00c4': 'Ä', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-',
        '\u2026': '...', '\u00a0': ' ', '\u200b': '', '\u200e': '',
        '\u200f': '', '\u202a': '', '\u202c': '', '\ufeff': '',
    }
    
    result = text
    for wrong, correct in turkish_mapping.items():
        result = result.replace(wrong, correct)
    
    result = re.sub(r'\s+', ' ', result)
    return result.strip()


def decode_and_fix_text(content: bytes) -> str:
    """Bytes'ı decode et ve Türkçe karakterleri düzelt"""
    encodings = ['utf-8', 'iso-8859-9', 'cp1254', 'windows-1254', 'latin-1']
    
    for encoding in encodings:
        try:
            decoded = content.decode(encoding)
            return normalize_turkish_text(decoded)
        except UnicodeDecodeError:
            continue
    
    try:
        decoded = content.decode('utf-8', errors='replace')
        return normalize_turkish_text(decoded)
    except:
        return content.decode('utf-8', errors='ignore')


def extract_simple_records(text: str):
    """Gelişmiş Kayıt Ayıklayıcı - Türkçe karakter düzeltmeli"""
    if not text:
        return []

    text = normalize_turkish_text(text)
    chunks = re.split(r'🧾 TC Sorgu Sonucu|📄 TC Sorgu Sonucu|🔍 TC Sorgu Sonucu', text)
    records = []

    for chunk in chunks:
        tc_match = re.search(r'TC\s*[:=]\s*(\d{11})', chunk)
        if not tc_match:
            continue

        record = {
            'TC': tc_match.group(1),
            'Ad': '',
            'Soyad': '',
            'DogumYeri': '',
            'DogumTarihi': '',
            'AnneAdi': '',
            'BabaAdi': '',
            'Il': '',
            'Ilce': '',
            'Telefon': '',
            'MedeniDurum': '',
            'Cinsiyet': ''
        }

        name_match = re.search(r'Adı Soyadı\s*[:=]\s*([^\n\r]+)|Ad Soyad\s*[:=]\s*([^\n\r]+)', chunk)
        if name_match:
            full_name = (name_match.group(1) or name_match.group(2) or '').strip().upper()
            parts = full_name.split()
            if parts:
                record['Ad'] = normalize_turkish_text(parts[0])
                record['Soyad'] = normalize_turkish_text(" ".join(parts[1:]) if len(parts) > 1 else "")

        birth_match = re.search(r'Doğum\s*\(Yer/Tarih\)\s*[:=]\s*([^/]+)\s*/\s*([\d-]+)', chunk)
        if not birth_match:
            birth_match = re.search(r'Doğum\s*[:=]\s*([^/]+)\s*/\s*([\d-]+)', chunk)
        if birth_match:
            record['DogumYeri'] = normalize_turkish_text(birth_match.group(1).strip().title())
            record['DogumTarihi'] = birth_match.group(2).strip()

        anne_match = re.search(r'Anne\s*\(Ad/TC\)\s*[:=]\s*([^/\n\r]+)', chunk)
        if anne_match:
            record['AnneAdi'] = normalize_turkish_text(anne_match.group(1).strip().upper())
        else:
            anne_match = re.search(r'Anne\s*[:=]\s*([^\n\r]+)', chunk)
            if anne_match:
                record['AnneAdi'] = normalize_turkish_text(anne_match.group(1).strip().upper())

        baba_match = re.search(r'Baba\s*\(Ad/TC\)\s*[:=]\s*([^/\n\r]+)', chunk)
        if baba_match:
            record['BabaAdi'] = normalize_turkish_text(baba_match.group(1).strip().upper())
        else:
            baba_match = re.search(r'Baba\s*[:=]\s*([^\n\r]+)', chunk)
            if baba_match:
                record['BabaAdi'] = normalize_turkish_text(baba_match.group(1).strip().upper())

        loc_match = re.search(r'İl/İlçe/Köy\s*[:=]\s*([^/]+)\s*/\s*([^/\n\r]+)', chunk)
        if loc_match:
            record['Il'] = normalize_turkish_text(loc_match.group(1).strip().title())
            record['Ilce'] = normalize_turkish_text(loc_match.group(2).strip().title())

        phone_match = re.search(r'GSM\s*[:=]\s*([^\n\r]+)', chunk)
        if not phone_match:
            phone_match = re.search(r'Telefon\s*[:=]\s*([^\n\r]+)', chunk)
        if phone_match:
            phone = re.sub(r'\D', '', phone_match.group(1))
            if phone and len(phone) >= 10:
                record['Telefon'] = phone[-10:]

        medeni_match = re.search(r'Medeni/Cinsiyet\s*[:=]\s*([^/]+)\s*/\s*([^\n\r]+)', chunk)
        if medeni_match:
            record['MedeniDurum'] = normalize_turkish_text(medeni_match.group(1).strip())
            record['Cinsiyet'] = normalize_turkish_text(medeni_match.group(2).strip())

        records.append(record)

    return records


def parse_general_response(text: str):
    """Genel parser - tüm komutlar için"""
    if not text:
        return []
    
    text = normalize_turkish_text(text)
    records = []
    
    chunks = re.split(r'🧾 TC Sorgu Sonucu|📄 TC Sorgu Sonucu|📱 GSM Sorgu Sonucu|👨‍👩‍👧‍👦 Aile Sorgu Sonucu|🚗 Plaka Sorgu Sonucu|={3,}|\-{3,}', text)
    
    for chunk in chunks:
        tc_match = re.search(r'TC\s*[:=]\s*(\d{11})', chunk)
        if not tc_match:
            gsm_match = re.search(r'GSM\s*[:=]\s*(\d{10,11})', chunk)
            plaka_match = re.search(r'Plaka\s*[:=]\s*([A-Z0-9]+)', chunk, re.IGNORECASE)
            if not gsm_match and not plaka_match:
                continue
        
        record = {
            'TC': '',
            'Ad': '',
            'Soyad': '',
            'DogumYeri': '',
            'DogumTarihi': '',
            'AnneAdi': '',
            'BabaAdi': '',
            'Il': '',
            'Ilce': '',
            'Telefon': '',
            'Plaka': '',
            'MarkaModel': '',
            'RuhsatNo': '',
            'MotorNo': '',
            'SaseNo': '',
            'IsyeriUnvani': '',
            'VergiNo': '',
            'AileSira': '',
            'BireySira': '',
            'Yakinlik': '',
            'Operator': '',
            'KayitTarihi': '',
            'Durum': '',
            'MedeniDurum': '',
            'Cinsiyet': ''
        }
        
        # TC
        if tc_match:
            record['TC'] = tc_match.group(1)
        
        # GSM
        gsm_match = re.search(r'GSM\s*[:=]\s*(\d{10})', chunk)
        if gsm_match:
            phone = gsm_match.group(1)
            if len(phone) == 10:
                record['Telefon'] = phone
        
        # Plaka
        plaka_match = re.search(r'Plaka\s*[:=]\s*([A-Z0-9]+)', chunk, re.IGNORECASE)
        if plaka_match:
            record['Plaka'] = plaka_match.group(1).upper()
        
        # Ad Soyad
        name_match = re.search(r'Adı Soyadı\s*[:=]\s*([^\n\r]+)|Ad Soyad\s*[:=]\s*([^\n\r]+)', chunk)
        if name_match:
            full_name = (name_match.group(1) or name_match.group(2) or '').strip().upper()
            parts = full_name.split()
            if parts:
                record['Ad'] = normalize_turkish_text(parts[0])
                record['Soyad'] = normalize_turkish_text(" ".join(parts[1:]) if len(parts) > 1 else "")
        
        # Doğum Yeri/Tarih
        birth_match = re.search(r'Doğum\s*\(Yer/Tarih\)\s*[:=]\s*([^/]+)\s*/\s*([\d-]+)', chunk)
        if not birth_match:
            birth_match = re.search(r'Doğum\s*[:=]\s*([^/]+)\s*/\s*([\d-]+)', chunk)
        if birth_match:
            record['DogumYeri'] = normalize_turkish_text(birth_match.group(1).strip().title())
            record['DogumTarihi'] = birth_match.group(2).strip()
        
        # Anne/Baba
        anne_match = re.search(r'Anne\s*\(Ad/TC\)\s*[:=]\s*([^/\n\r]+)', chunk)
        if anne_match:
            record['AnneAdi'] = normalize_turkish_text(anne_match.group(1).strip().upper())
        else:
            anne_match = re.search(r'Anne\s*[:=]\s*([^\n\r]+)', chunk)
            if anne_match:
                record['AnneAdi'] = normalize_turkish_text(anne_match.group(1).strip().upper())
            
        baba_match = re.search(r'Baba\s*\(Ad/TC\)\s*[:=]\s*([^/\n\r]+)', chunk)
        if baba_match:
            record['BabaAdi'] = normalize_turkish_text(baba_match.group(1).strip().upper())
        else:
            baba_match = re.search(r'Baba\s*[:=]\s*([^\n\r]+)', chunk)
            if baba_match:
                record['BabaAdi'] = normalize_turkish_text(baba_match.group(1).strip().upper())
        
        # İl/İlçe
        loc_match = re.search(r'İl/İlçe/Köy\s*[:=]\s*([^/]+)\s*/\s*([^/\n\r]+)', chunk)
        if loc_match:
            record['Il'] = normalize_turkish_text(loc_match.group(1).strip().title())
            record['Ilce'] = normalize_turkish_text(loc_match.group(2).strip().title())
        
        # Marka/Model
        model_match = re.search(r'Marka/Model\s*[:=]\s*([^\n\r]+)', chunk)
        if model_match:
            record['MarkaModel'] = normalize_turkish_text(model_match.group(1).strip())
        
        # Ruhsat No
        ruhsat_match = re.search(r'Ruhsat No\s*[:=]\s*([^\n\r]+)', chunk)
        if ruhsat_match:
            record['RuhsatNo'] = ruhsat_match.group(1).strip()
        
        # Motor No
        motor_match = re.search(r'Motor No\s*[:=]\s*([^\n\r]+)', chunk)
        if motor_match:
            record['MotorNo'] = motor_match.group(1).strip()
        
        # Şase No
        sase_match = re.search(r'Şase No\s*[:=]\s*([^\n\r]+)', chunk)
        if sase_match:
            record['SaseNo'] = sase_match.group(1).strip()
        
        # İşyeri Ünvanı
        unvan_match = re.search(r'Ünvan\s*[:=]\s*([^\n\r]+)|İşyeri Ünvanı\s*[:=]\s*([^\n\r]+)', chunk)
        if unvan_match:
            record['IsyeriUnvani'] = normalize_turkish_text((unvan_match.group(1) or unvan_match.group(2) or '').strip())
        
        # Vergi No
        vergi_match = re.search(r'Vergi No\s*[:=]\s*([^\n\r]+)', chunk)
        if vergi_match:
            record['VergiNo'] = vergi_match.group(1).strip()
        
        # Aile/Birey Sıra
        aile_match = re.search(r'Aile/Birey Sıra\s*[:=]\s*([^/]+)\s*/\s*([^\n\r]+)', chunk)
        if aile_match:
            record['AileSira'] = aile_match.group(1).strip()
            record['BireySira'] = aile_match.group(2).strip()
        
        # Yakınlık
        yakinlik_match = re.search(r'Yakınlık\s*[:=]\s*([^\n\r]+)', chunk)
        if yakinlik_match:
            record['Yakinlik'] = normalize_turkish_text(yakinlik_match.group(1).strip())
        
        # Operatör
        operator_match = re.search(r'Operatör\s*[:=]\s*([^\n\r]+)', chunk)
        if operator_match:
            record['Operator'] = normalize_turkish_text(operator_match.group(1).strip())
        
        # Kayıt Tarihi
        tarih_match = re.search(r'Kayıt Tarihi\s*[:=]\s*([^\n\r]+)', chunk)
        if tarih_match:
            record['KayitTarihi'] = tarih_match.group(1).strip()
        
        # Durum
        durum_match = re.search(r'Durum\s*[:=]\s*([^\n\r]+)', chunk)
        if durum_match:
            record['Durum'] = normalize_turkish_text(durum_match.group(1).strip())
        
        # Medeni Durum / Cinsiyet
        medeni_match = re.search(r'Medeni/Cinsiyet\s*[:=]\s*([^/]+)\s*/\s*([^\n\r]+)', chunk)
        if medeni_match:
            record['MedeniDurum'] = normalize_turkish_text(medeni_match.group(1).strip())
            record['Cinsiyet'] = normalize_turkish_text(medeni_match.group(2).strip())
        
        records.append(record)
    
    return records


# ========== TELEGRAM CLIENT MANAGEMENT ==========

async def get_or_create_client():
    """Thread-safe client oluştur veya mevcut client'ı döndür"""
    global client, loop
    
    with client_lock:
        if client is None:
            print("🔄 Creating new Telegram client...")
            if loop is None or loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            client = TelegramClient(
                StringSession(SESSION_STRING), 
                int(API_ID), 
                API_HASH,
                loop=loop,
                connection_retries=3,
                retry_delay=2,
                timeout=60,
                auto_reconnect=True
            )
        
        if not client.is_connected():
            print("🔗 Connecting Telegram client...")
            await client.connect()
            print("✅ Telegram client connected")
        
        return client


async def cleanup_client():
    """Client'ı güvenli şekilde kapat"""
    global client
    
    with client_lock:
        if client and client.is_connected():
            print("🔌 Disconnecting Telegram client...")
            try:
                await client.disconnect()
                print("✅ Telegram client disconnected")
            except:
                pass
            client = None


async def query_bot_with_command(command: str, timeout: int = 90):
    """Query the bot with given command and return raw text."""
    max_retries = 2
    retry_delay = 2
    
    for retry in range(max_retries):
        try:
            client = await get_or_create_client()
            
            async with client.conversation(BOT_USERNAME, timeout=timeout + 30) as conv:
                print(f"📤 Sending command: {command}")
                await conv.send_message(command)
                
                start_ts = time.time()
                raw_text = ""
                got_file = False
                
                while time.time() - start_ts < timeout:
                    try:
                        response = await conv.get_response(timeout=15)
                    except asyncio.TimeoutError:
                        print("⏳ Timeout waiting for response...")
                        continue
                    
                    text = getattr(response, 'text', '') or ''
                    
                    if text and any(word in text.lower() for word in ['sorgu yapılıyor', 'işlem devam', 'lütfen bekleyin', 'birazdan', 'yakında']):
                        print("⏳ Sorgu devam ediyor, bekleniyor...")
                        continue
                    
                    # Buton kontrolü
                    if hasattr(response, 'buttons') and response.buttons:
                        print("🔘 Buttons found, checking for download...")
                        for row in response.buttons:
                            for btn in row:
                                btn_text = str(getattr(btn, 'text', '')).lower()
                                if any(keyword in btn_text for keyword in ['txt', 'dosya', '.txt', 'indir', 'download', 'gör', 'aç']):
                                    print(f"📥 Found download button: {btn_text}")
                                    try:
                                        await btn.click()
                                        print("✅ Button clicked, waiting for file...")
                                        try:
                                            file_msg = await conv.get_response(timeout=20)
                                        except asyncio.TimeoutError:
                                            print("❌ Timeout waiting for file")
                                            continue
                                        
                                        if file_msg and hasattr(file_msg, 'media') and file_msg.media:
                                            print("📄 Downloading file...")
                                            file_path = await client.download_media(file_msg)
                                            if file_path and os.path.exists(file_path):
                                                try:
                                                    with open(file_path, 'rb') as f:
                                                        content = f.read()
                                                    
                                                    print(f"📊 File size: {len(content)} bytes")
                                                    raw_text = decode_and_fix_text(content)
                                                    got_file = True
                                                    print(f"✅ File downloaded and decoded, size: {len(raw_text)} chars")
                                                    
                                                finally:
                                                    try:
                                                        os.remove(file_path)
                                                    except:
                                                        pass
                                                
                                                if got_file:
                                                    return raw_text
                                    except Exception as e:
                                        print(f"❌ Button click error: {e}")
                                        continue
                    
                    # Direct media
                    if hasattr(response, 'media') and response.media:
                        print("📄 Message has media, downloading...")
                        try:
                            file_path = await client.download_media(response)
                            if file_path and os.path.exists(file_path):
                                with open(file_path, 'rb') as f:
                                    content = f.read()
                                
                                print(f"📊 Media file size: {len(content)} bytes")
                                raw_text = decode_and_fix_text(content)
                                
                                try:
                                    os.remove(file_path)
                                except:
                                    pass
                                
                                return raw_text
                        except Exception as e:
                            print(f"❌ Media download error: {e}")
                    
                    # Text data
                    if text:
                        text = normalize_turkish_text(text)
                        
                        if re.search(r'\d{11}', text) or re.search(r'GSM\s*[:=]\s*\d', text) or re.search(r'Plaka\s*[:=]', text, re.IGNORECASE):
                            raw_text = text
                            return raw_text
                        
                        if text.strip() and not any(word in text.lower() for word in ['sorgu yapılıyor', 'işlem devam']):
                            raw_text = text
                            return raw_text
                    
                    await asyncio.sleep(0.5)
                
                if raw_text:
                    return raw_text
                else:
                    return "❌ Sorgu zaman aşımına uğradı veya yanıt alınamadı"
                
        except Exception as e:
            print(f"❌ Query error (attempt {retry + 1}/{max_retries}): {e}")
            
            await cleanup_client()
            
            if retry < max_retries - 1:
                print(f"🔄 Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                return f"Error: {str(e)}"
    
    return "❌ Maximum retry attempts reached"


def sync_query_bot(command: str) -> str:
    """Async query'i sync context'te çalıştır"""
    global loop
    
    try:
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if not loop.is_running():
            result = loop.run_until_complete(query_bot_with_command(command))
        else:
            future = asyncio.run_coroutine_threadsafe(query_bot_with_command(command), loop)
            result = future.result(timeout=120)
        
        return result
        
    except RuntimeError as e:
        print(f"🔄 Runtime error: {e}, creating new loop")
        try:
            if loop and not loop.is_closed():
                loop.close()
        except:
            pass
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(query_bot_with_command(command))
        
    except Exception as e:
        print(f"❌ Sync query error: {e}")
        return f"Error: {str(e)}"


# ========== PARAMETRE TEMİZLEYİCİLER ==========

def clean_tc(tc):
    tc = re.sub(r'\D', '', tc)
    if len(tc) == 11:
        return tc
    return None

def clean_gsm(gsm):
    gsm = re.sub(r'\D', '', gsm)
    if gsm.startswith('0'):
        gsm = gsm[1:]
    if len(gsm) == 10:
        return gsm
    elif len(gsm) > 10:
        return gsm[-10:]
    return None

def clean_plaka(plaka):
    plaka = re.sub(r'[^A-Z0-9]', '', plaka.upper())
    if len(plaka) >= 4:
        return plaka
    return None


# ========== CACHE MANAGEMENT ==========

def add_to_cache(key, value):
    """Cache'e timestamp ile ekle"""
    result_cache[key] = {
        'data': value,
        'timestamp': time.time()
    }


def get_from_cache(key):
    """Cache'den timestamp kontrolü ile al"""
    if key in result_cache:
        cache_entry = result_cache[key]
        if isinstance(cache_entry, dict) and 'timestamp' in cache_entry:
            if time.time() - cache_entry['timestamp'] <= 300:  # 5 dakika
                return cache_entry['data']
            else:
                result_cache.pop(key, None)
    return None


def cleanup_cache():
    """Eski cache'leri temizle"""
    global result_cache
    
    current_time = time.time()
    keys_to_remove = []
    
    for key, value in result_cache.items():
        if isinstance(value, dict) and 'timestamp' in value:
            if current_time - value['timestamp'] > 600:  # 10 dakika
                keys_to_remove.append(key)
    
    for key in keys_to_remove:
        result_cache.pop(key, None)
    
    if keys_to_remove:
        print(f"🧹 {len(keys_to_remove)} adet eski cache temizlendi")


# ========== TEXT FORMATTER ==========

def format_records_to_text(records, title="Sorgu Sonuçları"):
    """Kayıtları text formatına dönüştür"""
    if not records:
        return "❌ Kayıt bulunamadı.\n"
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {title} - {len(records)} KAYIT")
    lines.append(f"{'='*60}\n")
    
    for i, rec in enumerate(records, 1):
        lines.append(f"🔸 KAYIT {i}")
        lines.append(f"{'-'*40}")
        
        # TC varsa ekle
        if rec.get('TC'):
            lines.append(f"🪪 TC: {rec['TC']}")
        
        # Ad Soyad varsa ekle
        if rec.get('Ad') or rec.get('Soyad'):
            ad = rec.get('Ad', '')
            soyad = rec.get('Soyad', '')
            lines.append(f"👤 Ad Soyad: {ad} {soyad}".strip())
        
        # Doğum bilgileri
        if rec.get('DogumYeri') or rec.get('DogumTarihi'):
            dogum_text = "🎂 Doğum: "
            if rec.get('DogumYeri'):
                dogum_text += rec['DogumYeri']
            if rec.get('DogumTarihi'):
                if rec.get('DogumYeri'):
                    dogum_text += " / "
                dogum_text += rec['DogumTarihi']
            lines.append(dogum_text)
        
        # Anne/Baba
        if rec.get('AnneAdi'):
            lines.append(f"👩 Anne: {rec['AnneAdi']}")
        if rec.get('BabaAdi'):
            lines.append(f"👨 Baba: {rec['BabaAdi']}")
        
        # İl/İlçe
        if rec.get('Il') or rec.get('Ilce'):
            ilce_text = "📍 Yer: "
            if rec.get('Il'):
                ilce_text += rec['Il']
            if rec.get('Ilce'):
                if rec.get('Il'):
                    ilce_text += " / "
                ilce_text += rec['Ilce']
            lines.append(ilce_text)
        
        # Telefon
        if rec.get('Telefon'):
            lines.append(f"📱 Telefon: {rec['Telefon']}")
        
        # Plaka
        if rec.get('Plaka'):
            lines.append(f"🚗 Plaka: {rec['Plaka']}")
        
        # Marka/Model
        if rec.get('MarkaModel'):
            lines.append(f"🏍️ Marka/Model: {rec['MarkaModel']}")
        
        # Ruhsat No
        if rec.get('RuhsatNo'):
            lines.append(f"📄 Ruhsat No: {rec['RuhsatNo']}")
        
        # Motor No
        if rec.get('MotorNo'):
            lines.append(f"⚙️ Motor No: {rec['MotorNo']}")
        
        # Şase No
        if rec.get('SaseNo'):
            lines.append(f"🔧 Şase No: {rec['SaseNo']}")
        
        # İşyeri Ünvanı
        if rec.get('IsyeriUnvani'):
            lines.append(f"🏢 İşyeri: {rec['IsyeriUnvani']}")
        
        # Vergi No
        if rec.get('VergiNo'):
            lines.append(f"💰 Vergi No: {rec['VergiNo']}")
        
        # Aile/Birey Sıra
        if rec.get('AileSira') or rec.get('BireySira'):
            aile_text = "👨‍👩‍👧‍👦 Sıra: "
            if rec.get('AileSira'):
                aile_text += f"Aile: {rec['AileSira']}"
            if rec.get('BireySira'):
                if rec.get('AileSira'):
                    aile_text += " / "
                aile_text += f"Birey: {rec['BireySira']}"
            lines.append(aile_text)
        
        # Yakınlık
        if rec.get('Yakinlik'):
            lines.append(f"🤝 Yakınlık: {rec['Yakinlik']}")
        
        # Medeni Durum / Cinsiyet
        if rec.get('MedeniDurum') or rec.get('Cinsiyet'):
            medeni_text = "💍 Medeni/Cinsiyet: "
            if rec.get('MedeniDurum'):
                medeni_text += rec['MedeniDurum']
            if rec.get('Cinsiyet'):
                if rec.get('MedeniDurum'):
                    medeni_text += " / "
                medeni_text += rec['Cinsiyet']
            lines.append(medeni_text)
        
        # Durum
        if rec.get('Durum'):
            lines.append(f"📊 Durum: {rec['Durum']}")
        
        # Kayıt Tarihi
        if rec.get('KayitTarihi'):
            lines.append(f"📅 Kayıt Tarihi: {rec['KayitTarihi']}")
        
        # Operatör
        if rec.get('Operator'):
            lines.append(f"👨‍💻 Operatör: {rec['Operator']}")
        
        lines.append("")
    
    lines.append(f"{'='*60}")
    lines.append(f"✅ Toplam {len(records)} kayıt listelendi")
    lines.append(f"{'='*60}")
    
    return '\n'.join(lines)


# ========== APP INITIALIZATION ==========

def init_app():
    """Uygulama başlangıcında çalışır"""
    global app_started
    
    if not app_started:
        print("🎬 Initializing application...")
        app_started = True
        
        # Başlangıçta basit bir test yap
        try:
            test_command = "/ad TEST TEST"
            print(f"🔧 Running startup test: {test_command}")
            result = sync_query_bot(test_command)
            print(f"🔧 Startup test result length: {len(result)}")
            if "Error:" in result or "❌" in result:
                print(f"⚠️ Startup test warning: {result[:100]}")
            else:
                print("✅ Startup test completed successfully")
        except Exception as e:
            print(f"⚠️ Startup test error (non-critical): {e}")


# ========== ORTAK ENDPOINT HANDLER ==========

def handle_bot_query(command, params, cache_prefix, return_raw=False):
    """Ortak bot sorgu handler'ı"""
    cache_key = f"{cache_prefix}_{params}"
    cached = get_from_cache(cache_key)
    if cached and not return_raw:
        print(f"📦 Cache hit for {cache_prefix}: {params}")
        return cached
    
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    print(f"📊 Raw response length: {len(raw_text)}")
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text,
            'raw_preview': ""
        }
    else:
        records = parse_general_response(raw_text)

        if records:
            result = {
                'success': True,
                'query': command,
                'count': len(records),
                'records': records,
                'raw_preview': raw_text[:500] if raw_text else ""
            }
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'raw_preview': raw_text[:500] if raw_text else ""
            }
    
    add_to_cache(cache_key, result)
    
    if return_raw:
        return raw_text
    
    return result


# ========== TÜM ENDPOINT'LER ==========

def get_output_format():
    """Çıktı formatını belirle"""
    format_param = request.args.get('format', 'json').lower()
    if format_param in ['text', 'txt', 'plain']:
        return 'text'
    return 'json'


@app.route('/query', methods=['GET'])
def api_query():
    """Ana sorgu endpoint'i"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    name = name.strip().upper()
    surname = surname.strip().upper()

    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400

    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    result = handle_bot_query(command, f"{name}_{surname}_{il}_{adres}", "query")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} Sorgu Sonuçları"
            if il:
                title += f" - İl: {il}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/ad', methods=['GET'])
def api_ad():
    """Ad soyad sorgusu"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()

    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400

    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    result = handle_bot_query(command, f"{name}_{surname}_{il}_{adres}", "ad")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} Sorgu Sonuçları"
            if il:
                title += f" - İl: {il}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/tc', methods=['GET'])
def api_tc():
    """TC sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/tc {tc}"
    result = handle_bot_query(command, tc, "tc")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC: {tc} Sorgu Sonuçları"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/tc2', methods=['GET'])
def api_tc2():
    """TC2 sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/tc2 {tc}"
    result = handle_bot_query(command, tc, "tc2")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC2: {tc} Sorgu Sonuçları"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/gsm', methods=['GET'])
def api_gsm():
    """GSM sorgusu"""
    if not app_started:
        init_app()
    
    gsm = request.args.get('gsm', '').strip()
    gsm = clean_gsm(gsm)
    
    if not gsm:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir telefon numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir telefon numarası giriniz'}), 400
    
    command = f"/gsm {gsm}"
    result = handle_bot_query(command, gsm, "gsm")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"GSM: {gsm} Sorgu Sonuçları"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/gsm2', methods=['GET'])
def api_gsm2():
    """GSM2 sorgusu"""
    if not app_started:
        init_app()
    
    gsm = request.args.get('gsm', '').strip()
    gsm = clean_gsm(gsm)
    
    if not gsm:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir telefon numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir telefon numarası giriniz'}), 400
    
    command = f"/gsm2 {gsm}"
    result = handle_bot_query(command, gsm, "gsm2")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"GSM2: {gsm} Sorgu Sonuçları"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/aile', methods=['GET'])
def api_aile():
    """Aile sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/aile {tc}"
    result = handle_bot_query(command, tc, "aile")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"Aile Sorgusu - TC: {tc}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/sulale', methods=['GET'])
def api_sulale():
    """Sülale sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/sulale {tc}"
    result = handle_bot_query(command, tc, "sulale")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"Sülale Sorgusu - TC: {tc}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/hane', methods=['GET'])
def api_hane():
    """Hane sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/hane {tc}"
    result = handle_bot_query(command, tc, "hane")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"Hane Sorgusu - TC: {tc}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/isyeri', methods=['GET'])
def api_isyeri():
    """İşyeri sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/isyeri {tc}"
    result = handle_bot_query(command, tc, "isyeri")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"İşyeri Sorgusu - TC: {tc}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/plaka', methods=['GET'])
def api_plaka():
    """Plaka sorgusu"""
    if not app_started:
        init_app()
    
    plaka = request.args.get('plaka', '').strip()
    plaka = clean_plaka(plaka)
    
    if not plaka:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir plaka numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir plaka numarası giriniz'}), 400
    
    command = f"/plaka {plaka}"
    result = handle_bot_query(command, plaka, "plaka")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"Plaka: {plaka} Sorgu Sonuçları"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/vesika', methods=['GET'])
def api_vesika():
    """Vesika sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir 11 haneli TC kimlik numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    command = f"/vesika {tc}"
    result = handle_bot_query(command, tc, "vesika")
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"Vesika Sorgusu - TC: {tc}"
            text_output = format_records_to_text(result['records'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)


@app.route('/text', methods=['GET'])
def api_text():
    """Text output endpoint (legacy)"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    name = name.strip().upper()
    surname = surname.strip().upper()

    if not name or not surname:
        return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')

    command = f"/ad {name} {surname}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    print(f"📊 Raw response length: {len(raw_text)}")
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        return Response(f'❌ Hata: {raw_text}', content_type='text/plain; charset=utf-8')
    
    records = extract_simple_records(raw_text)

    if not records:
        return Response(f'❌ {name} {surname} için kayıt bulunamadı.', content_type='text/plain; charset=utf-8')

    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {name} {surname} - {len(records)} KAYIT")
    lines.append(f"{'='*60}\n")

    for i, rec in enumerate(records, 1):
        lines.append(f"🔸 KAYIT {i}")
        lines.append(f"{'-'*40}")
        if rec['Ad'] or rec['Soyad']:
            lines.append(f"👤 Ad Soyad: {rec['Ad']} {rec['Soyad']}")
        lines.append(f"🪪 TC: {rec['TC']}")
        if rec['DogumYeri'] or rec['DogumTarihi']:
            birth = f"🎂 Doğum: {rec['DogumYeri']}" if rec['DogumYeri'] else "🎂 Doğum: "
            if rec['DogumTarihi']:
                birth += f" / {rec['DogumTarihi']}"
            lines.append(birth)
        if rec['AnneAdi']:
            lines.append(f"👩 Anne: {rec['AnneAdi']}")
        if rec['BabaAdi']:
            lines.append(f"👨 Baba: {rec['BabaAdi']}")
        if rec['Il'] or rec['Ilce']:
            location = []
            if rec['Il']:
                location.append(rec['Il'])
            if rec['Ilce']:
                location.append(rec['Ilce'])
            if location:
                lines.append(f"📍 Yer: {' / '.join(location)}")
        if rec['Telefon']:
            lines.append(f"📱 Telefon: {rec['Telefon']}")
        lines.append("")

    lines.append(f"{'='*60}")
    lines.append(f"✅ Toplam {len(records)} kayıt listelendi")
    lines.append(f"{'='*60}")

    return Response('\n'.join(lines), content_type='text/plain; charset=utf-8')


@app.route('/raw', methods=['GET'])
def api_raw():
    """Ham veri endpoint'i"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    name = name.strip().upper()
    surname = surname.strip().upper()

    if not name or not surname:
        return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')

    command = f"/ad {name} {surname}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    print(f"📊 Raw response length: {len(raw_text)}")
    
    output = f"🔍 HAM VERİ: {name} {surname}\n"
    output += "="*60 + "\n\n"
    output += raw_text[:2000] + ("\n\n[...truncated...]" if len(raw_text) > 2000 else "")

    return Response(output, content_type='text/plain; charset=utf-8')


@app.route('/test', methods=['GET'])
def api_test():
    """Test endpoint"""
    return jsonify({
        'status': '✅ API çalışıyor',
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'app_started': app_started,
        'cache_size': len(result_cache),
        'endpoints': [
            {'name': 'Ad Soyad (JSON)', 'url': '/query?name=EYMEN&surname=YAVUZ'},
            {'name': 'Ad Soyad (Text)', 'url': '/query?name=EYMEN&surname=YAVUZ&format=text'},
            {'name': 'TC (JSON)', 'url': '/tc?tc=11111111110'},
            {'name': 'TC (Text)', 'url': '/tc?tc=11111111110&format=text'},
            {'name': 'GSM (JSON)', 'url': '/gsm?gsm=5346149118'},
            {'name': 'GSM (Text)', 'url': '/gsm?gsm=5346149118&format=text'},
            {'name': 'Plaka (JSON)', 'url': '/plaka?plaka=34AKP34'},
            {'name': 'Plaka (Text)', 'url': '/plaka?plaka=34AKP34&format=text'},
        ]
    })


@app.route('/health', methods=['GET'])
def api_health():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'service': 'TC Sorgu API',
        'text_support': True,
        'endpoints_with_text': 'Tüm endpointler ?format=text parametresi ile text çıktısı verebilir'
    })


@app.route('/')
def index():
    """Home page"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>🔍 TC Sorgu API</title>
        <style>
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                margin: 0; 
                padding: 20px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }
            .container { 
                max-width: 1000px; 
                margin: 0 auto; 
                background: white; 
                padding: 30px; 
                border-radius: 15px; 
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }
            h1 { 
                color: #333; 
                text-align: center; 
                margin-bottom: 10px;
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }
            .endpoint { 
                background: #f8f9fa; 
                padding: 15px; 
                border-left: 5px solid #007bff; 
                border-radius: 8px;
            }
            .category {
                margin-top: 30px;
                padding-bottom: 10px;
                border-bottom: 2px solid #6c757d;
                color: #495057;
            }
            code { 
                background: #e9ecef; 
                padding: 3px 8px; 
                border-radius: 4px; 
                font-family: 'Courier New', monospace;
                color: #d63384;
                font-size: 0.9em;
                display: block;
                margin: 5px 0;
                overflow-x: auto;
            }
            .test-link {
                display: inline-block;
                background: #28a745;
                color: white;
                padding: 6px 12px;
                border-radius: 5px;
                margin-top: 8px;
                text-decoration: none !important;
                font-size: 0.85em;
                margin-right: 5px;
            }
            .test-link.json {
                background: #007bff;
            }
            .test-link.text {
                background: #17a2b8;
            }
            .test-link:hover {
                opacity: 0.9;
                color: white;
            }
            .format-info {
                background: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 5px;
                padding: 10px;
                margin: 15px 0;
                font-size: 0.9em;
            }
            .footer {
                text-align: center;
                margin-top: 40px;
                color: #6c757d;
                font-size: 0.9em;
                padding-top: 20px;
                border-top: 1px solid #dee2e6;
            }
            @media (max-width: 768px) {
                .container { padding: 15px; }
                .grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1><span>🔍</span> TC Sorgu API</h1>
            <p style="text-align: center; color: #666;">Telegram bot üzerinden gelişmiş sorgulama API'sı</p>
            
            <div class="format-info">
                <strong>📝 Çıktı Formatları:</strong><br>
                • <strong>JSON Format:</strong> Varsayılan format (?format=json veya parametre yok)<br>
                • <strong>Text Format:</strong> <code>?format=text</code> parametresi ekleyin<br>
                • <strong>Örnek:</strong> <code>/query?name=EYMEN&surname=YAVUZ&format=text</code>
            </div>
            
            <div class="category">
                <h3>👤 Kişi Sorguları</h3>
            </div>
            <div class="grid">
                <div class="endpoint">
                    <h4>Ad Soyad Sorgusu</h4>
                    <code>GET /query?name=EYMEN&surname=YAVUZ</code>
                    <code>GET /ad?name=EYMEN&surname=YAVUZ</code>
                    <a href="/query?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/query?name=EYMEN&surname=YAVUZ&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>TC Sorgusu</h4>
                    <code>GET /tc?tc=11111111110</code>
                    <a href="/tc?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/tc?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>TC2 Sorgusu</h4>
                    <code>GET /tc2?tc=11111111110</code>
                    <a href="/tc2?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/tc2?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
            </div>
            
            <div class="category">
                <h3>📱 İletişim Sorguları</h3>
            </div>
            <div class="grid">
                <div class="endpoint">
                    <h4>GSM Sorgusu</h4>
                    <code>GET /gsm?gsm=5346149118</code>
                    <a href="/gsm?gsm=5346149118" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/gsm?gsm=5346149118&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>GSM2 Sorgusu</h4>
                    <code>GET /gsm2?gsm=5346149118</code>
                    <a href="/gsm2?gsm=5346149118" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/gsm2?gsm=5346149118&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
            </div>
            
            <div class="category">
                <h3>👨‍👩‍👧‍👦 Aile Sorguları</h3>
            </div>
            <div class="grid">
                <div class="endpoint">
                    <h4>Aile Sorgusu</h4>
                    <code>GET /aile?tc=11111111110</code>
                    <a href="/aile?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/aile?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>Sülale Sorgusu</h4>
                    <code>GET /sulale?tc=11111111110</code>
                    <a href="/sulale?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/sulale?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>Hane Sorgusu</h4>
                    <code>GET /hane?tc=11111111110</code>
                    <a href="/hane?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/hane?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
            </div>
            
            <div class="category">
                <h3>📊 Diğer Sorgular</h3>
            </div>
            <div class="grid">
                <div class="endpoint">
                    <h4>İşyeri Sorgusu</h4>
                    <code>GET /isyeri?tc=11111111110</code>
                    <a href="/isyeri?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/isyeri?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>Plaka Sorgusu</h4>
                    <code>GET /plaka?plaka=34AKP34</code>
                    <a href="/plaka?plaka=34AKP34" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/plaka?plaka=34AKP34&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
                
                <div class="endpoint">
                    <h4>Vesika Sorgusu</h4>
                    <code>GET /vesika?tc=11111111110</code>
                    <a href="/vesika?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                    <a href="/vesika?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
                </div>
            </div>
            
            <div class="category">
                <h3>🔧 Yardımcı Endpoint'ler</h3>
            </div>
            <div class="grid">
                <div class="endpoint">
                    <h4>Text Output (Legacy)</h4>
                    <code>GET /text?name=EYMEN&surname=YAVUZ</code>
                    <a href="/text?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link">Test Et</a>
                </div>
                
                <div class="endpoint">
                    <h4>Raw Output</h4>
                    <code>GET /raw?name=EYMEN&surname=YAVUZ</code>
                    <a href="/raw?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link">Test Et</a>
                </div>
                
                <div class="endpoint">
                    <h4>Test & Health</h4>
                    <code>GET /test</code>
                    <code>GET /health</code>
                    <a href="/test" target="_blank" class="test-link json">Test Et</a>
                </div>
            </div>
            
            <div class="footer">
                <p><strong>⚠️ Not:</strong> Tüm endpoint'ler UTF-8 encoding kullanır. Cache süresi 5 dakikadır.</p>
                <p>© 2024 TC Sorgu API - Render Deployment</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


# ========== APPLICATION LIFECYCLE ==========

# Startup
print("🚀 Application starting...")
init_app()

# Cleanup at exit
import atexit

@atexit.register
def cleanup():
    """Uygulama kapatıldığında çalışır"""
    print("🛑 Cleaning up resources...")
    
    global client, loop
    
    with client_lock:
        if client and client.is_connected():
            try:
                if loop and not loop.is_closed():
                    loop.run_until_complete(client.disconnect())
                    print("✅ Telegram client disconnected on exit")
            except:
                pass
            client = None
        
        if loop and not loop.is_closed():
            try:
                loop.close()
            except:
                pass
            loop = None


# ========== MAIN ==========
if __name__ == '__main__':
    print(f"🌐 Server starting on port {PORT}")
    print("📋 Available endpoints:")
    print("  👤 /query - Ad soyad sorgusu (JSON/Text)")
    print("  👤 /ad - Ad soyad sorgusu (JSON/Text)")
    print("  🪪 /tc - TC sorgusu (JSON/Text)")
    print("  🪪 /tc2 - TC2 sorgusu (JSON/Text)")
    print("  📱 /gsm - GSM sorgusu (JSON/Text)")
    print("  📱 /gsm2 - GSM2 sorgusu (JSON/Text)")
    print("  👨‍👩‍👧‍👦 /aile - Aile sorgusu (JSON/Text)")
    print("  🌳 /sulale - Sülale sorgusu (JSON/Text)")
    print("  🏠 /hane - Hane sorgusu (JSON/Text)")
    print("  🏢 /isyeri - İşyeri sorgusu (JSON/Text)")
    print("  🚗 /plaka - Plaka sorgusu (JSON/Text)")
    print("  🖼 /vesika - Vesika sorgusu (JSON/Text)")
    print("  📝 /text - Text çıktısı (legacy)")
    print("  🔍 /raw - Ham veri")
    print("  🧪 /test - Test endpoint")
    print("  ❤️ /health - Health check")
    print("  🏠 / - Ana sayfa")
    print("")
    print("📝 Tüm endpoint'lere ?format=text parametresi ekleyerek text çıktısı alabilirsiniz!")
    
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
