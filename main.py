from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from sqlalchemy import orm
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from forms import LoginForm, RegisterForm
import os
from werkzeug.utils import secure_filename
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = '1234567890'
global_init("db/banks.sqlite")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
UPLOAD_FOLDER = 'static/avatars'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@login_manager.user_loader
def load_user(user_id_):
    db_sess = create_session()
    return db_sess.get(User, user_id_)


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
        user.password = form.password.data
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
    user_bank = bank_entry.bank if bank_entry and bank_entry.bank else {}
    words_list = list(user_bank.keys())
    word = None
    if words_list:
        word = random.choice(words_list)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'word_bank':
            return redirect('/words')

        if action == 'button_input_word':
            if len(words_list) < 2:
                flash('Добавьте минимум 2 слова в банк, чтобы начать тренировку!', 'warning')
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
    user = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    user_bank = user.bank
    if request.method == 'POST':
        action = request.form.get('action')
        add_word = request.form.get('add_word')
        home = request.form.get('home')
        if add_word:
            new_word = request.form.get('new_word')
            new_translation = request.form.get('new_translation')
            user_bank[new_word] = new_translation
            user.bank = user_bank
            orm.attributes.flag_modified(user, "bank")
            db_sess.commit()
        elif action:
            del user_bank[action]
            user.bank = user_bank
            orm.attributes.flag_modified(user, "bank")
            db_sess.commit()
        elif home:
            return redirect('/main')
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
    else:
        flash('Недопустимый формат файла', 'danger')
    return redirect(url_for('main'))


@app.route('/alice', methods=['POST'])
def alice_webhook():
    request_data = request.json
    user_id = request_data['session']['user_id']  # Уникальный ID пользователя Алисы

    # Инициализируем ответ
    response = {
        "version": request_data['version'],
        "session": request_data['session'],
        "response": {
            "end_session": False
        }
    }

    db_sess = create_session()
    # В реальности тут лучше использовать Account Linking,
    # но для простоты ищем по какому-то полю или создаем запись
    bank_entry = db_sess.query(Bank).filter(Bank.alice_id == user_id).first()

    if not bank_entry or not bank_entry.bank or len(bank_entry.bank) < 2:
        response["response"][
            "text"] = "Привет! В твоем банке мало слов. Зайди на сайт, чтобы добавить хотя бы два слова."
        return jsonify(response)

    user_bank = bank_entry.bank
    words_list = list(user_bank.keys())

    # Если это новое посещение (начало диалога)
    if request_data['session']['new']:
        word = random.choice(words_list)
        response["response"]["text"] = f"Привет! Давай тренироваться. Как переводится слово {word}?"
        # Сохраняем загаданное слово в session_state, чтобы Алиса его помнила
        response["session_state"] = {"current_word": word}
        return jsonify(response)

    # Логика проверки ответа
    state = request_data.get('state', {}).get('session', {})
    current_word = state.get('current_word')
    user_answer = request_data['request']['command'].lower().strip()

    if not current_word:  # Если состояние потерялось
        word = random.choice(words_list)
        response["response"]["text"] = f"Что-то я забыла слово. Давай заново. Как переводится {word}?"
        response["session_state"] = {"current_word": word}
        return jsonify(response)

    correct_answer = user_bank.get(current_word, "").lower()

    if user_answer == correct_answer:
        new_word = random.choice([w for w in words_list if w != current_word])
        response["response"]["text"] = f"Правильно! Следующее слово: {new_word}."
        response["session_state"] = {"current_word": new_word}
    else:
        response["response"]["text"] = f"Не совсем. Попробуй еще раз: {current_word}?"
        response["session_state"] = {"current_word": current_word}

    return jsonify(response)


if __name__ == '__main__':
    app.run()
