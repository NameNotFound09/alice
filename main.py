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
import json


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
    global word, word_translation
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


def alice_response(text, buttons=None, end_session=False):
    """Формирует стандартный ответ в формате Алисы."""
    response = {
        "response": {
            "text": text,
            "buttons": buttons or [],
            "end_session": end_session
        },
        "version": "1.0"
    }
    return jsonify(response)

@app.route('/alice', methods=['POST'])
def alice_webhook():
    req = request.json
    user_id = req['session']['user_id']
    command = req['request'].get('command', '').lower()
    session_state = req.get('state', {}).get('session', {})
    
    # Инициализация сессии или получение из состояния
    db_sess = create_session()
    # Предполагаем, что у Алисы свой "пользователь" в БД. 
    # Если его нет, создаем или привязываем к гостевому ID.
    bank_entry = db_sess.query(Bank).filter(Bank.id == user_id).first()
    if not bank_entry:
        # Для простоты создаем запись, если ее нет (или используйте заглушку)
        bank_entry = Bank(id=user_id, bank={})
        db_sess.add(bank_entry)
        db_sess.commit()

    user_bank = bank_entry.bank

    # --- ЛОГИКА ДИАЛОГА ---
    
    # 1. Помощь
    if 'помощь' in command or 'что ты умеешь' in command:
        return alice_response(
            "Я помогу учить слова! Вы можете сказать: "
            "'Добавь слово: перевод', 'Удали слово', 'Очисти банк' или 'Список слов'.",
            buttons=[{"title": "Список слов", "hide": True}, {"title": "Очистить банк", "hide": True}]
        )

    # 2. Очистка банка
    if 'очисти' in command or 'очистить' in command:
        bank_entry.bank = {}
        db_sess.commit()
        return alice_response("Банк слов успешно очищен.")

    # 3. Просмотр слов
    if 'список' in command or 'покажи' in command:
        if not user_bank:
            return alice_response("Ваш банк слов пуст.")
        words_str = ", ".join([f"{k} - {v}" for k, v in user_bank.items()])
        return alice_response(f"Ваши слова: {words_str}")

    # 4. Удаление слова (режим или команда)
    if 'удали' in command or 'удалить' in command:
        # Пытаемся вытащить слово из команды (например, "удали собака")
        parts = command.split()
        if len(parts) > 1:
            word_to_del = parts[1]
            if word_to_del in user_bank:
                del user_bank[word_to_del]
                db_sess.commit()
                return alice_response(f"Слово {word_to_del} удалено.")
            return alice_response("Такого слова нет в банке.")
        return alice_response("Какое слово удалить?")

    # 5. Добавление слова - Способ 1: Прямая команда (формат: слово перевод)
    # Пример: "Добавь кошка cat"
    if 'добавь' in command:
        parts = command.split()
        if len(parts) >= 3:
            word = parts[1]
            translation = " ".join(parts[2:])
            user_bank[word] = translation
            db_sess.commit()
            return alice_response(f"Добавлено: {word} - {translation}", 
                                  buttons=[{"title": "Еще добавить", "hide": True}])
        
        # Если формат неверный, переходим в диалоговый режим (способ 2)
        return alice_response("Какое слово и перевод добавить? Скажите, например: 'Кошка, Кэт'.",
                              buttons=[{"title": "Помощь", "hide": True}])

    # 6. Режим ожидания (если пользователь ранее что-то начал)
    # Здесь можно добавить логику проверки сессии, если нужно хранить контекст
    
    return alice_response("Я вас не совсем поняла. Скажите 'помощь', чтобы узнать, что я умею.")

#


if __name__ == '__main__':
    app.run()
