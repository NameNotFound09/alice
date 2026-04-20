import os
import random
import json
import logging
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from sqlalchemy import orm

from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from forms import LoginForm, RegisterForm

app = Flask(__name__)
app.config['SECRET_KEY'] = 'stable_production_key_450_lines'
app.config['JSON_AS_ASCII'] = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(BASE_DIR, 'db')
if not os.path.exists(db_dir):
    os.makedirs(db_dir)

db_path = os.path.join(db_dir, 'banks.sqlite')
global_init(db_path)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def get_initial_structure():
    """Возвращает стандартную структуру данных банка."""
    return {
        "words": {},
        "stats": {
            "score": 0,
            "level": 1,
            "correct": 0,
            "wrong": 0,
            "streak": 0,
            "max_streak": 0
        },
        "achievements": [],
        "history": []
    }


def format_word_count(n):
    """Склонение слова 'слово' для Алисы."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} слово"
    elif n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
        return f"{n} слова"
    return f"{n} слов"


def clean_text_input(text):
    """Очистка входящего текста по стандарту."""
    if not text:
        return ""
    text = text.lower().strip()
    chars_to_remove = '.,!?;:-—()"'
    for char in chars_to_remove:
        text = text.replace(char, ' ')
    return " ".join(text.split())


@login_manager.user_loader
def load_user(user_id):
    db_sess = create_session()
    user = db_sess.query(User).get(user_id)
    db_sess.close()
    return user


@app.route('/')
def index_redirect():
    return redirect(url_for('main_dashboard'))


@app.route('/main')
@login_required
def main_dashboard():
    db_sess = create_session()
    bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    if not bank_entry:
        db_sess.close()
        return "Ошибка доступа к данным банка."
    
    if isinstance(bank_entry.bank, str):
        data = json.loads(bank_entry.bank)
    else:
        data = bank_entry.bank
    db_sess.close()
    
    display_words = {}
    for k, v in data.get('words', {}).items():
        if isinstance(v, dict):
            display_words[k] = v.get('translation', '—')
        else:
            display_words[k] = v
            
    return render_template(
        'main.html',
        words=display_words,
        stats=data.get('stats', {}),
        achs=data.get('achievements', [])
    )


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('main_dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        user = db_sess.query(User).filter(
            User.login == form.username.data
        ).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            db_sess.close()
            return redirect(url_for('main_dashboard'))
        flash('Неверные учетные данные', 'danger')
        db_sess.close()
    return render_template('login.html', form=form)


@app.route('/register', methods=['GET', 'POST'])
def register_page():
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()
        check_user = db_sess.query(User).filter(
            User.login == form.username.data
        ).first()
        if check_user:
            flash("Этот логин уже занят", "warning")
            db_sess.close()
            return render_template('register.html', form=form)
        
        new_user = User()
        new_user.login = form.username.data
        new_user.set_password(form.password.data)
        db_sess.add(new_user)
        db_sess.commit()
        
        new_bank = Bank()
        new_bank.id = new_user.id
        new_bank.bank = get_initial_structure()
        db_sess.add(new_bank)
        db_sess.commit()
        db_sess.close()
        
        flash("Регистрация завершена успешно!", "success")
        return redirect(url_for('login_page'))
    return render_template('register.html', form=form)


@app.route('/alice', methods=['POST'])
def alice_webhook():
    req = request.json
    u_id = req['session']['user_id']
    raw_cmd = req['request']['command']
    cmd = clean_text_input(raw_cmd)
    
    if 'state' in req and 'session' in req['state']:
        state = req['state']['session']
    else:
        state = {}
        
    db_sess = create_session()
    entry = db_sess.query(Bank).filter(Bank.alice_id == u_id).first()
    
    if entry is None:
        entry = Bank()
        entry.alice_id = u_id
        entry.bank = get_initial_structure()
        db_sess.add(entry)
        db_sess.commit()
        
    if isinstance(entry.bank, str):
        full_data = json.loads(entry.bank)
    else:
        full_data = entry.bank
        
    words = full_data.get('words', {})
    stats = full_data.get('stats', {})
    
    res = {
        "version": req['version'],
        "session": req['session'],
        "response": {
            "end_session": False,
            "buttons": [
                {"title": "Учить", "hide": True},
                {"title": "Добавить слово", "hide": True},
                {"title": "Статистика", "hide": True}
            ]
        },
        "session_state": state
    }

    if cmd in ["стоп", "выход", "закрой", "хватит"]:
        res['response']['text'] = "Хорошо, до встречи в следующий раз!"
        res['response']['end_session'] = True
        db_sess.close()
        return jsonify(res)

    if state.get('action') == 'wait_trans':
        ru_key = state.get('tmp_ru')
        words[ru_key] = {
            "translation": raw_cmd,
            "date": datetime.now().isoformat()
        }
        full_data['words'] = words
        entry.bank = full_data
        orm.attributes.flag_modified(entry, "bank")
        db_sess.commit()
        res['response']['text'] = f"Записала! '{ru_key}' — это '{raw_cmd}'."
        res['session_state'] = {}
        db_sess.close()
        return jsonify(res)

    if state.get('action') == 'wait_ru':
        if not raw_cmd:
            res['response']['text'] = "Я не расслышала. Какое слово добавить?"
            return jsonify(res)
        res['response']['text'] = f"Слово '{raw_cmd}'. Назовите его перевод."
        res['session_state'] = {"action": "wait_trans", "tmp_ru": raw_cmd}
        db_sess.close()
        return jsonify(res)

    if state.get('mode') == 'quiz':
        target = state.get('current_q')
        # Обработка разных структур хранения
        if isinstance(words[target], dict):
            correct = words[target]['translation']
        else:
            correct = words[target]
            
        if clean_text_input(raw_cmd) == clean_text_input(correct):
            stats['score'] += 10
            stats['correct'] += 1
            stats['streak'] += 1
            if stats['streak'] > stats['max_streak']:
                stats['max_streak'] = stats['streak']
                
            if stats['score'] >= stats['level'] * 100:
                stats['level'] += 1
                m = f"Верно! Новый уровень: {stats['level']}! "
            else:
                m = "Правильно! "
                
            full_data['stats'] = stats
            entry.bank = full_data
            orm.attributes.flag_modified(entry, "bank")
            db_sess.commit()
            
            keys = list(words.keys())
            nxt = random.choice(keys)
            res['response']['text'] = m + f"Как переводится '{nxt}'?"
            res['session_state'] = {"mode": "quiz", "current_q": nxt}
            db_sess.close()
            return jsonify(res)
            
        elif cmd in ["сдаюсь", "пропустить", "не знаю"]:
            stats['wrong'] += 1
            stats['streak'] = 0
            full_data['stats'] = stats
            entry.bank = full_data
            orm.attributes.flag_modified(entry, "bank")
            db_sess.commit()
            
            keys = list(words.keys())
            nxt = random.choice(keys)
            res['response']['text'] = (
                f"Правильный ответ: {correct}. "
                f"Давайте другое: '{nxt}'?"
            )
            res['session_state'] = {"mode": "quiz", "current_q": nxt}
            db_sess.close()
            return jsonify(res)
        else:
            res['response']['text'] = f"Нет, это не '{raw_cmd}'. Попробуйте еще раз!"
            db_sess.close()
            return jsonify(res)

    if cmd in ["добавить", "добавить слово"]:
        res['response']['text'] = "Какое слово на русском языке добавим в словарь?"
        res['session_state'] = {"action": "wait_ru"}
        db_sess.close()
        return jsonify(res)

    if cmd in ["учить", "тренировка"]:
        w_keys = list(words.keys())
        if len(w_keys) < 1:
            res['response']['text'] = "В вашем словаре пока нет слов. Добавьте их."
        else:
            q_word = random.choice(w_keys)
            res['response']['text'] = f"Начнем. Как переводится слово '{q_word}'?"
            res['session_state'] = {"mode": "quiz", "current_q": q_word}
        db_sess.close()
        return jsonify(res)

    if cmd in ["статистика", "прогресс", "рекорды"]:
        msg = (
            f"Ваша статистика: \n"
            f"Уровень: {stats.get('level', 1)}. \n"
            f"Очков: {stats.get('score', 0)}. \n"
            f"Верных ответов: {stats.get('correct', 0)}. \n"
            f"Рекордная серия: {stats.get('max_streak', 0)}."
        )
        res['response']['text'] = msg
        db_sess.close()
        return jsonify(res)

    if cmd in ["помощь", "что ты умеешь", "справка"]:
        help_msg = (
            "Я помогаю запоминать иностранные слова. \n"
            "Вы можете сказать 'Добавить слово', 'Тренировка' или 'Статистика'. \n"
            "Для выхода просто скажите 'Хватит'."
        )
        res['response']['text'] = help_msg
        db_sess.close()
        return jsonify(res)

    if req['session']['new']:
        count_text = format_word_count(len(words))
        res['response']['text'] = (
            f"Рада видеть! В вашем словаре {count_text}. "
            f"Что выберете: тренировку или новое слово?"
        )
    else:
        res['response']['text'] = "Я не совсем поняла. Попробуйте сказать 'Помощь'."

    db_sess.close()
    return jsonify(res)


if __name__ == '__main__':
    srv_port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=srv_port)