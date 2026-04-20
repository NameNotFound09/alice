import os
import random
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

# --- Основные роуты ---

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
        user.set_password(form.password.data) # Предполагается наличие метода хеширования
        db_sess.add(user)
        db_sess.flush()

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

    user_bank = bank_entry.bank if bank_entry.bank else {}
    words_list = list(user_bank.keys())
    
    # Логика выбора слова для тренировки
    word = random.choice(words_list) if words_list else None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'word_bank':
            return redirect('/words')

        if action == 'button_input_word':
            if len(words_list) < 2:
                flash('Добавьте минимум 2 слова в банк!', 'warning')
                return redirect(url_for('main'))

            current_word = request.form.get('current_word')
            user_translation = request.form.get('translation', '').strip().lower()
            correct_translation = user_bank.get(current_word, "").lower()

            if user_translation == correct_translation:
                flash('Правильно!', 'success')
                new_word = random.choice([w for w in words_list if w != current_word])
                return render_template('main.html', word=new_word)
            else:
                flash('Неверно, попробуйте еще раз', 'danger')
                return render_template('main.html', word=current_word)

    return render_template('main.html', word=word)

@app.route('/words', methods=['GET', 'POST'])
@login_required
def words():
    db_sess = create_session()
    user_bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    user_bank = user_bank_entry.bank or {}

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

@app.route('/update_avatar', methods=['POST'])
@login_required
def update_avatar():
    if 'avatar_file' not in request.files:
        flash('Файл не выбран', 'danger')
        return redirect(url_for('main'))

    file = request.files['avatar_file']
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = secure_filename(f"user_{current_user.id}.{ext}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        db_sess = create_session()
        user = db_sess.get(User, current_user.id)
        user.avatar_path = f"avatars/{filename}"
        db_sess.commit()
        flash('Аватар обновлен!', 'success')
    return redirect(url_for('main'))

# --- АЛИСА (WEBHOOK) ---

@app.route('/alice', methods=['POST'])
def alice_webhook():
    request_data = request.json
    user_id = request_data['session']['user_id']
    
    response = {
        "version": request_data['version'],
        "session": request_data['session'],
        "response": {"end_session": False}
    }

    db_sess = create_session()
    # Ищем по alice_id (убедитесь, что это поле есть в модели Bank)
    bank_entry = db_sess.query(Bank).filter(Bank.alice_id == user_id).first()

    if not bank_entry:
        bank_entry = Bank(alice_id=user_id, bank={})
        db_sess.add(bank_entry)
        db_sess.commit()

    user_bank = bank_entry.bank or {}
    words_list = list(user_bank.keys())
    user_command = request_data['request']['command'].lower().strip()
    
    # Получаем состояние из предыдущего хода
    session_state = request_data.get('state', {}).get('session', {})
    current_word = session_state.get('current_word')

    # 1. Обработка команд управления
    if user_command in ['помощь', 'что ты умеешь', 'команды']:
        response["response"]["text"] = (
            "Я помогу учить слова! Можно сказать: 'Добавь слово яблоко — apple', "
            "'Покажи слова' или 'Удали слово яблоко'. Также я буду спрашивать перевод!"
        )
        return jsonify(response)

    if user_command == 'покажи слова':
        if not user_bank:
            response["response"]["text"] = "Твой банк пуст."
        else:
            msg = "\n".join([f"{k} — {v}" for k, v in user_bank.items()])
            response["response"]["text"] = f"Твои слова:\n{msg}"
        return jsonify(response)

    if user_command.startswith('добавь слово'):
        raw = user_command.replace('добавь слово', '').strip()
        sep = '—' if '—' in raw else '-'
        if sep in raw:
            w, t = [x.strip() for x in raw.split(sep, 1)]
            user_bank[w] = t
            bank_entry.bank = user_bank
            orm.attributes.flag_modified(bank_entry, "bank")
            db_sess.commit()
            response["response"]["text"] = f"Добавила: {w}"
        else:
            response["response"]["text"] = "Скажи: добавь слово [слово] — [перевод]"
        return jsonify(response)

    # 2. Логика тренировки
    if len(words_list) < 2:
        response["response"]["text"] = "В банке мало слов. Добавь хотя бы два!"
        return jsonify(response)

    # Если только зашли или нет текущего слова - задаем новый вопрос
    if request_data['session']['new'] or not current_word:
        new_w = random.choice(words_list)
        response["response"]["text"] = f"Начнем! Как переводится '{new_w}'?"
        response["session_state"] = {"current_word": new_w}
        return jsonify(response)

    # Проверка ответа пользователя
    correct = user_bank.get(current_word, "").lower()
    if user_command == correct:
        next_w = random.choice([w for w in words_list if w != current_word])
        response["response"]["text"] = f"Верно! А '{next_w}'?"
        response["session_state"] = {"current_word": next_w}
    else:
        response["response"]["text"] = f"Нет, не угадал. Попробуй еще раз: '{current_word}'?"
        response["session_state"] = {"current_word": current_word}

    return jsonify(response)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)