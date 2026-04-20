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
app.config['SECRET_KEY'] = 'pep8_compliant_dictionary_450_lines'
app.config['JSON_AS_ASCII'] = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("App")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(BASE_DIR, 'db')):
    os.makedirs(os.path.join(BASE_DIR, 'db'))

db_path = os.path.join(BASE_DIR, 'db', 'banks.sqlite')
global_init(db_path)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def get_empty_bank_data():
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


def clean_user_text(text):
    if text is None:
        return ""
    text = text.lower().strip()
    symbols = ".,!?;:-()\""
    for s in symbols:
        text = text.replace(s, "")
    return " ".join(text.split())


@login_manager.user_loader
def load_user_func(user_id):
    db_sess = create_session()
    user = db_sess.query(User).get(user_id)
    db_sess.close()
    return user


@app.route('/')
def route_index():
    return redirect('/main')


@app.route('/main')
@login_required
def route_main():
    db_sess = create_session()
    entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    if not entry:
        db_sess.close()
        return "System error: Data not found."
    if isinstance(entry.bank, str):
        data = json.loads(entry.bank)
    else:
        data = entry.bank
    db_sess.close()
    simple_words = {}
    for key in data['words']:
        if isinstance(data['words'][key], dict):
            simple_words[key] = data['words'][key]['translation']
        else:
            simple_words[key] = data['words'][key]
    return render_template(
        'main.html',
        words=simple_words,
        stats=data['stats'],
        achs=data['achievements']
    )


@app.route('/login', methods=['GET', 'POST'])
def route_login():
    if current_user.is_authenticated:
        return redirect('/main')
    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        user = db_sess.query(User).filter(
            User.login == form.username.data
        ).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            db_sess.close()
            return redirect("/main")
        flash('Неверный логин или пароль', 'danger')
        db_sess.close()
    return render_template('login.html', form=form)


@app.route('/register', methods=['GET', 'POST'])
def route_register():
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()
        existing = db_sess.query(User).filter(
            User.login == form.username.data
        ).first()
        if existing:
            flash("Этот логин уже занят", "warning")
            db_sess.close()
            return render_template('register.html', form=form)
        user = User()
        user.login = form.username.data
        user.set_password(form.password.data)
        db_sess.add(user)
        db_sess.commit()
        bank = Bank()
        bank.id = user.id
        bank.bank = get_empty_bank_data()
        db_sess.add(bank)
        db_sess.commit()
        db_sess.close()
        flash("Вы успешно зарегистрировались!", "success")
        return redirect(url_for('route_login'))
    return render_template('register.html', form=form)


@app.route('/alice', methods=['POST'])
def alice_webhook_main():
    req = request.json
    user_id = req['session']['user_id']
    raw_command = req['request']['command']
    command = clean_user_text(raw_command)
    if 'state' in req and 'session' in req['state']:
        state = req['state']['session']
    else:
        state = {}
    db_sess = create_session()
    entry = db_sess.query(Bank).filter(Bank.alice_id == user_id).first()
    if entry is None:
        entry = Bank()
        entry.alice_id = user_id
        entry.bank = get_empty_bank_data()
        db_sess.add(entry)
        db_sess.commit()
    if isinstance(entry.bank, str):
        full_data = json.loads(entry.bank)
    else:
        full_data = entry.bank
    words = full_data['words']
    stats = full_data['stats']
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

    if command in ["стоп", "выход", "закрой"]:
        res['response']['text'] = "До встречи! Хорошего дня."
        res['response']['end_session'] = True
        db_sess.close()
        return jsonify(res)

    if state.get('action') == 'waiting_for_translation':
        word_rus = state.get('temp_rus')
        word_eng = raw_command
        words[word_rus] = {
            "translation": word_eng,
            "added_at": datetime.now().isoformat(),
            "level": 0
        }
        full_data['words'] = words
        entry.bank = full_data
        orm.attributes.flag_modified(entry, "bank")
        db_sess.commit()
        res['response']['text'] = f"Записала! {word_rus} — {word_eng}."
        res['session_state'] = {}
        db_sess.close()
        return jsonify(res)

    if state.get('action') == 'waiting_for_word':
        res['response']['text'] = f"Хорошо, '{raw_command}'. Какой перевод?"
        res['session_state'] = {
            "action": "waiting_for_translation",
            "temp_rus": raw_command
        }
        db_sess.close()
        return jsonify(res)

    if state.get('mode') == 'training':
        target_word = state.get('current_q')
        correct_answer = words[target_word]['translation']
        if clean_user_text(raw_command) == clean_user_text(correct_answer):
            stats['score'] += 10
            stats['correct'] += 1
            stats['streak'] += 1
            if stats['streak'] > stats['max_streak']:
                stats['max_streak'] = stats['streak']
            if stats['score'] >= stats['level'] * 100:
                stats['level'] += 1
                msg = f"Верно! Новый уровень: {stats['level']}! "
            else:
                msg = "Правильно! "
            all_keys = list(words.keys())
            next_q = random.choice(all_keys)
            full_data['stats'] = stats
            entry.bank = full_data
            orm.attributes.flag_modified(entry, "bank")
            db_sess.commit()
            res['response']['text'] = msg + f"Как переводится '{next_q}'?"
            res['session_state'] = {"mode": "training", "current_q": next_q}
            db_sess.close()
            return jsonify(res)
        elif command in ["сдаюсь", "пропустить", "не знаю"]:
            stats['wrong'] += 1
            stats['streak'] = 0
            all_keys = list(words.keys())
            next_q = random.choice(all_keys)
            full_data['stats'] = stats
            entry.bank = full_data
            orm.attributes.flag_modified(entry, "bank")
            db_sess.commit()
            res['response']['text'] = (
                f"Это было '{correct_answer}'. "
                f"Попробуем другое: '{next_q}'?"
            )
            res['session_state'] = {"mode": "training", "current_q": next_q}
            db_sess.close()
            return jsonify(res)
        else:
            res['response']['text'] = (
                f"Нет, это не '{raw_command}'. "
                f"Попробуй еще раз или скажи 'сдаюсь'."
            )
            db_sess.close()
            return jsonify(res)

    if command in ["добавить", "добавить слово"]:
        res['response']['text'] = "Какое слово на русском добавим?"
        res['session_state'] = {"action": "waiting_for_word"}
        db_sess.close()
        return jsonify(res)

    if command in ["учить", "тренировка"]:
        all_keys = list(words.keys())
        if len(all_keys) < 1:
            res['response']['text'] = "В словаре пусто. Добавьте слова."
        else:
            q = random.choice(all_keys)
            res['response']['text'] = f"Начнем. Как переводится '{q}'?"
            res['session_state'] = {"mode": "training", "current_q": q}
        db_sess.close()
        return jsonify(res)

    if command in ["статистика", "прогресс"]:
        txt = (
            f"Уровень: {stats['level']}. "
            f"Очки: {stats['score']}. "
            f"Верно: {stats['correct']}. "
            f"Серия: {stats['max_streak']}."
        )
        res['response']['text'] = txt
        db_sess.close()
        return jsonify(res)

    if command in ["помощь", "что ты умеешь"]:
        h = (
            "Я помогаю учить слова. \n"
            "Скажите 'Добавить' - для нового слова. \n"
            "Скажите 'Учить' - для проверки. \n"
            "Скажите 'Статистика' - для прогресса."
        )
        res['response']['text'] = h
        db_sess.close()
        return jsonify(res)

    if req['session']['new']:
        res['response']['text'] = (
            f"Привет! В вашем словаре {len(words)} слов. "
            f"Что будем делать сегодня?"
        )
    else:
        res['response']['text'] = "Я вас не поняла. Скажите 'Помощь'."

    db_sess.close()
    return jsonify(res)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)