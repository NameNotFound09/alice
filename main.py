import os
import random
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from sqlalchemy import orm, Column, String, Integer, JSON, ForeignKey
from werkzeug.utils import secure_filename

from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from forms import LoginForm, RegisterForm

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev_key_alice_pro_v3_99'
logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(BASE_DIR, 'db')
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, 'banks.sqlite')
global_init(db_path)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def get_safe_bank(entry):
    if not entry or not entry.bank:
        return {"words": {}, "stats": {"score": 0, "level": 1}, "history": []}
    if isinstance(entry.bank, str):
        try:
            return json.loads(entry.bank)
        except:
            return {"words": {}, "stats": {"score": 0, "level": 1}, "history": []}
    return entry.bank

def clean_text(text):
    if not text: return ""
    text = text.lower().strip()
    for char in '.,!?;:-—"()':
        text = text.replace(char, ' ')
    return " ".join(text.split())

@login_manager.user_loader
def load_user(user_id_):
    db_sess = create_session()
    return db_sess.get(User, user_id_)

@app.route('/')
def index():
    return redirect('/main')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect('/main')
    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        user = db_sess.query(User).filter(User.login == form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect("/main")
        flash('Ошибка входа', 'danger')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect('/main')
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()
        if db_sess.query(User).filter(User.login == form.username.data).first():
            flash("Логин занят", "warning")
            return render_template('register.html', form=form)
        user = User(login=form.username.data)
        user.set_password(form.password.data)
        db_sess.add(user)
        db_sess.flush()
        new_bank = Bank(id=user.id, bank={"words": {}, "stats": {"score": 0, "level": 1}})
        db_sess.add(new_bank)
        db_sess.commit()
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/main')
@login_required
def main():
    db_sess = create_session()
    bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    data = get_safe_bank(bank_entry)
    return render_template('main.html', words=data.get("words", {}), stats=data.get("stats", {}))

@app.route('/alice', methods=['POST'])
def alice_webhook():
    try:
        req = request.json
        user_id = req['session']['user_id']
        db_sess = create_session()
        bank_entry = db_sess.query(Bank).filter(Bank.alice_id == user_id).first()
        
        if not bank_entry:
            bank_entry = Bank(alice_id=user_id, bank={"words": {}, "stats": {"score": 0, "level": 1}})
            db_sess.add(bank_entry)
            db_sess.commit()

        full_data = get_safe_bank(bank_entry)
        user_bank = full_data.get("words", {})
        stats = full_data.get("stats", {"score": 0, "level": 1})
        
        raw_command = req['request']['command']
        command = clean_text(raw_command)
        state = req.get('state', {}).get('session', {})
        
        res = {
            "version": req['version'],
            "session": req['session'],
            "response": {"end_session": False, "buttons": []},
            "session_state": state
        }

        # Логика кнопок по умолчанию
        res["response"]["buttons"] = [
            {"title": "Учить", "hide": True},
            {"title": "Мои слова", "hide": True},
            {"title": "Добавить слово", "hide": False},
            {"title": "Статистика", "hide": True}
        ]

        # 1. Сценарий: Новый пользователь или приветствие
        if not command or req['session']['new']:
            res["response"]["text"] = f"Рада видеть! Твой текущий уровень: {stats.get('level')}. Начнем тренировку или добавим слова?"
            res["response"]["tts"] = f"Рада в+идеть! Твой тек+ущий +уровень: {stats.get('level')}. Начн+ем тренир+овку или доб+авим слов+а?"
            return jsonify(res)

        # 2. Сценарий: Статистика
        if command in ['статистика', 'уровень', 'мой прогресс']:
            score = stats.get('score', 0)
            count = len(user_bank)
            res["response"]["text"] = f"Твой счет: {score} очков. В словаре: {count} слов. Уровень: {stats.get('level')}."
            return jsonify(res)

        # 3. Сценарий: Добавление слова (Пошаговый режим)
        if command == 'добавить слово' and not state.get('action'):
            res["response"]["text"] = "Какое слово хочешь выучить?"
            res["session_state"] = {"action": "wait_word"}
            return jsonify(res)

        if state.get('action') == 'wait_word':
            res["response"]["text"] = f"Поняла, запоминаем '{raw_command}'. Какой у него перевод?"
            res["session_state"] = {"action": "wait_translation", "new_word": raw_command}
            return jsonify(res)

        if state.get('action') == 'wait_translation':
            word = state.get('new_word')
            user_bank[word] = raw_command
            full_data["words"] = user_bank
            bank_entry.bank = full_data
            orm.attributes.flag_modified(bank_entry, "bank")
            db_sess.commit()
            res["response"]["text"] = f"Успех! '{word}' теперь в твоем списке. Продолжим?"
            res["session_state"] = {}
            return jsonify(res)

        # 4. Сценарий: Быстрое добавление (через тире)
        for sep in ['—', '-', 'тире', 'это']:
            if sep in command:
                parts = raw_command.lower().replace('добавь', '').split(sep)
                if len(parts) >= 2:
                    w, t = parts[0].strip(), parts[1].strip()
                    user_bank[w] = t
                    full_data["words"] = user_bank
                    bank_entry.bank = full_data
                    orm.attributes.flag_modified(bank_entry, "bank")
                    db_sess.commit()
                    res["response"]["text"] = f"Добавила: {w} — {t}. Учим дальше?"
                    return jsonify(res)

        # 5. Сценарий: Удаление
        if any(x in command for x in ['удали', 'забудь', 'выкинь']):
            target = command.replace('удали', '').replace('забудь', '').replace('слово', '').strip()
            if target in user_bank:
                del user_bank[target]
                full_data["words"] = user_bank
                bank_entry.bank = full_data
                orm.attributes.flag_modified(bank_entry, "bank")
                db_sess.commit()
                res["response"]["text"] = f"Слово '{target}' удалено."
            else:
                res["response"]["text"] = f"Не нашла слова '{target}'."
            return jsonify(res)

        # 6. Сценарий: Тренировка
        words_list = list(user_bank.keys())
        if command in ['учить', 'давай', 'играть', 'старт'] or state.get('current_word'):
            if len(words_list) < 2:
                res["response"]["text"] = "В словаре мало слов. Добавь хотя бы два, чтобы начать."
                return jsonify(res)

            current_q = state.get('current_word')
            
            if not current_q:
                new_q = random.choice(words_list)
                res["response"]["text"] = f"Как переводится '{new_q}'?"
                res["session_state"] = {"current_word": new_q}
                return jsonify(res)
            
            correct = user_bank.get(current_q, "").lower().strip()
            if command == clean_text(correct):
                stats['score'] = stats.get('score', 0) + 5
                if stats['score'] > stats['level'] * 50:
                    stats['level'] += 1
                full_data['stats'] = stats
                bank_entry.bank = full_data
                orm.attributes.flag_modified(bank_entry, "bank")
                db_sess.commit()
                
                next_q = random.choice([w for w in words_list if w != current_q])
                res["response"]["text"] = f"Верно! +5 очков. А как будет '{next_q}'?"
                res["response"]["tts"] = f"<speaker audio=\"alice-sounds-game-ping-1.opus\"> В+ерно! Плюс пять очк+ов. А как б+удет {next_q}?"
                res["session_state"] = {"current_word": next_q}
            else:
                if any(x in command for x in ['сдаюсь', 'пропусти', 'не знаю']):
                    next_q = random.choice([w for w in words_list if w != current_q])
                    res["response"]["text"] = f"Жаль. '{current_q}' это '{correct}'. Давай другое: '{next_q}'?"
                    res["session_state"] = {"current_word": next_q}
                else:
                    res["response"]["text"] = f"Нет, не '{raw_command}'. Попробуй еще раз или скажи 'сдаюсь'."
                    res["session_state"] = {"current_word": current_q}
            return jsonify(res)

        res["response"]["text"] = "Я тебя не совсем поняла. Попробуй сказать 'Помощь'."
        return jsonify(res)

    except Exception as e:
        return jsonify({"version": "1.0", "response": {"text": "Ошибка в системе. Попробуйте позже."}, "end_session": True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)