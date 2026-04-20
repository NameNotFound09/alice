import os
import random
import json
from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from sqlalchemy import orm
from werkzeug.utils import secure_filename

# Импорты ваших локальных модулей
from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from forms import LoginForm, RegisterForm

app = Flask(__name__)
app.config['SECRET_KEY'] = '1234567890'

# --- Настройки путей ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(BASE_DIR, 'db')
avatar_dir = os.path.join(BASE_DIR, 'static', 'avatars')

os.makedirs(db_dir, exist_ok=True)
os.makedirs(avatar_dir, exist_ok=True)

db_path = os.path.join(db_dir, 'banks.sqlite')
global_init(db_path)

# --- Настройка Flask-Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

app.config['UPLOAD_FOLDER'] = 'static/avatars'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id_):
    db_sess = create_session()
    return db_sess.get(User, user_id_)

# --- Вспомогательная функция для работы с JSON в БД ---
def get_bank_dict(entry):
    if not entry or not entry.bank:
        return {}
    if isinstance(entry.bank, str):
        try:
            return json.loads(entry.bank)
        except:
            return {}
    return entry.bank

# --- Основные роуты сайта ---

@app.route('/')
def index():
    return redirect('/main')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/main')
    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        user = db_sess.query(User).filter(User.login == form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect("/main")
        else:
            flash('Неверный логин или пароль', 'danger')
    return render_template('login.html', title='Вход', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect('/main')
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()
        if db_sess.query(User).filter(User.login == form.username.data).first():
            flash("Этот логин уже занят", "danger")
            return render_template('register.html', form=form)

        user = User()
        user.login = form.username.data
        user.set_password(form.password.data)
        db_sess.add(user)
        db_sess.flush()

        # При создании указываем только id (alice_id пустой)
        new_bank = Bank(id=user.id, bank={})
        db_sess.add(new_bank)
        db_sess.commit()

        flash("Регистрация успешна!", "success")
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/")

@app.route('/main', methods=['GET', 'POST'])
@login_required
def main():
    db_sess = create_session()
    bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()

    if not bank_entry:
        bank_entry = Bank(id=current_user.id, bank={})
        db_sess.add(bank_entry)
        db_sess.commit()

    user_bank = get_bank_dict(bank_entry)
    words_list = list(user_bank.keys())
    word = random.choice(words_list) if words_list else None

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'word_bank':
            return redirect('/words')

        if action == 'button_input_word':
            if len(words_list) < 2:
                flash('Добавьте минимум 2 слова!', 'warning')
                return redirect(url_for('main'))

            current_word = request.form.get('current_word')
            user_translation = request.form.get('translation', '').strip().lower()
            correct_translation = user_bank.get(current_word, "").lower()

            if user_translation == correct_translation:
                flash('Правильно!', 'success')
                new_word = random.choice([w for w in words_list if w != current_word])
                return render_template('main.html', word=new_word)
            else:
                flash('Неверно!', 'danger')
                return render_template('main.html', word=current_word)

    return render_template('main.html', word=word)

@app.route('/words', methods=['GET', 'POST'])
@login_required
def words():
    db_sess = create_session()
    user_bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    user_bank = get_bank_dict(user_bank_entry)

    if request.method == 'POST':
        if 'add_word' in request.form:
            new_word = request.form.get('new_word', '').strip()
            new_translation = request.form.get('new_translation', '').strip()
            if new_word and new_translation:
                user_bank[new_word] = new_translation
                user_bank_entry.bank = user_bank
                orm.attributes.flag_modified(user_bank_entry, "bank")
                db_sess.commit()

        elif 'delete_word' in request.form:
            word_to_del = request.form.get('delete_word')
            if word_to_del in user_bank:
                del user_bank[word_to_del]
                user_bank_entry.bank = user_bank
                orm.attributes.flag_modified(user_bank_entry, "bank")
                db_sess.commit()
        return redirect(url_for('words'))

    return render_template('words.html', words=user_bank)

# --- АЛИСА (WEBHOOK) ---

@app.route('/alice', methods=['POST'])
def alice_webhook():
    try:
        request_data = request.json
        user_id = request_data['session']['user_id']
        
        res = {
            "version": request_data['version'],
            "session": request_data['session'],
            "response": {"end_session": False},
            "session_state": {} 
        }

        db_sess = create_session()
        bank_entry = db_sess.query(Bank).filter(Bank.alice_id == user_id).first()

        # Если записи нет, создаем новую. 
        # ВАЖНО: убедитесь, что в модели Bank id имеет autoincrement=True
        if not bank_entry:
            bank_entry = Bank(alice_id=user_id, bank={})
            db_sess.add(bank_entry)
            db_sess.commit()

        user_bank = get_bank_dict(bank_entry)
        words_list = list(user_bank.keys())
        user_command = request_data['request']['command'].lower().strip()
        
        session_state = request_data.get('state', {}).get('session', {})
        current_word = session_state.get('current_word')

        # 1. Обработка команд
        if user_command in ['помощь', 'что ты умеешь']:
            res["response"]["text"] = "Я учу слова. Скажи: 'Добавь слово яблоко — apple'."
            return jsonify(res)

        if user_command.startswith('добавь слово'):
            raw = user_command.replace('добавь слово', '').strip()
            sep = '—' if '—' in raw else '-'
            if sep in raw:
                w, t = [x.strip() for x in raw.split(sep, 1)]
                user_bank[w] = t
                bank_entry.bank = user_bank
                orm.attributes.flag_modified(bank_entry, "bank")
                db_sess.commit()
                res["response"]["text"] = f"Записала: {w}."
            else:
                res["response"]["text"] = "Нужно сказать: Добавь слово [слово] тире [перевод]."
            return jsonify(res)

        # 2. Логика тренировки
        if len(words_list) < 2:
            res["response"]["text"] = "В твоем словаре мало слов. Добавь хотя бы два."
            return jsonify(res)

        if request_data['session'].get('new') or not current_word:
            new_w = random.choice(words_list)
            res["response"]["text"] = f"Начнем! Как переводится '{new_w}'?"
            res["session_state"] = {"current_word": new_w}
            return jsonify(res)

        correct_answer = user_bank.get(current_word, "").lower()
        if user_command == correct_answer:
            next_w = random.choice([w for w in words_list if w != current_word])
            res["response"]["text"] = f"Верно! А '{next_w}'?"
            res["session_state"] = {"current_word": next_w}
        else:
            res["response"]["text"] = f"Нет. Попробуй еще раз: '{current_word}'?"
            res["session_state"] = {"current_word": current_word}

        return jsonify(res)

    except Exception as e:
        print(f"ALICE ERROR: {e}")
        # Возвращаем понятную ошибку вместо 500
        return jsonify({
            "version": "1.0",
            "response": {"text": f"Ошибка: {str(e)}", "end_session": True}
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)