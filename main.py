from flask import Flask, render_template, request, redirect, flash, url_for
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


@app.route('/alice', methods=['POST'])
def alice_skill():
    req = request.json
    session = create_session()
    alice_user_id = req['session']['user']['user_id']
    bank_record = session.query(Bank).filter(Bank.alice_id == alice_user_id).first()

    if not bank_record:
        bank_record = Bank(alice_id=alice_user_id, bank={})
        session.add(bank_record)
        session.commit()

    user_data = bank_record.bank or {}
    command = req['request']['command'].lower().strip()
    state = user_data.get('state', 'main')
    response_text = ""
    suggested_actions = []

    # Приветствие и главное меню
    if command in ['привет', 'здравствуй', 'start', 'начало', 'запусти', 'приветик']:
        user_data['state'] = 'main'
        session.commit()
        response_text = (
            "Привет! Я — помощник для изучения английских слов! 🌟\n\n"
            "Доступные команды:\n"
            "• 'новое слово' — добавить слово с переводом\n"
            "• 'мои слова' — посмотреть все слова\n"
            "• 'тест' — начать тренировку\n"
            "• 'режим теста' — выбрать тип тренировки\n"
            "• 'удалить слово' — удалить конкретное слово\n"
            "• 'очистить все' — удалить все слова\n"
            "• 'статистика' — посмотреть прогресс\n"
            "• 'помощь' — показать подсказки\n\n"
            "Что будем делать?"
        )
        suggested_actions = [
            {"title": "Новое слово", "hide": True},
            {"title": "Мои слова", "hide": True},
            {"title": "Тест", "hide": True}
        ]

    # Помощь с подробными подсказками
    elif command == 'помощь':
        response_text = (
            "📚 Команды помощника:\n\n"
            "1. 'новое слово' → добавь слово:перевод (например, hello:привет)\n"
            "2. 'мои слова' → показать все сохранённые слова\n"
            "3. 'тест' → начать тренировку перевода\n"
            "4. 'режим теста' → выбрать тип тренировки:\n"
            "   - 'английский → русский'\n"
            "   - 'русский → английский'\n"
            "5. 'удалить слово hello' → удалить конкретное слово\n"
            "6. 'очистить все' → удалить все слова\n"
            "7. 'статистика' → посмотреть прогресс изучения\n"
            "8. 'совет' → получить рекомендацию по учёбе\n"
            "9. 'привет' → вернуться в главное меню\n\n"
            "Чем могу помочь?"
        )

    # Выбор режима теста
    elif command == 'режим теста':
        user_data['state'] = 'choosing_test_mode'
        session.commit()
        response_text = (
            "🎯 Выбери режим тренировки:\n"
            "1. 'английский → русский' — перевод с английского\n"
            "2. 'русский → английский' — перевод на английский\n"
            "Напиши номер или название режима."
        )

    elif user_data.get('state') == 'choosing_test_mode':
        if '1' in command or 'английский' in command:
            user_data['test_mode'] = 'en_ru'
            response_text = "Режим: английский → русский. Начни тренировку командой 'тест'."
        elif '2' in command or 'русский' in command:
            user_data['test_mode'] = 'ru_en'
            response_text = "Режим: русский → английский. Начни тренировку командой 'тест'."
        else:
            response_text = "Не понял режим. Выбери 1 или 2."
        user_data['state'] = 'main'
        session.commit()

    # Добавление нового слова с улучшенной валидацией
    elif 'новое слово' in command:
        user_data['state'] = 'waiting_word'
        session.commit()
        response_text = "📝 Напиши слово и его перевод через двоеточие. Например: hello:привет"

    elif user_data.get('state') == 'waiting_word':
        if ':' in command:
            try:
                word, translation = command.split(':', 1)
                word, translation = word.strip().lower(), translation.strip()
                if not word or not translation:
                    response_text = "❌ Пустое слово или перевод. Попробуй ещё раз."
                elif len(word) > 50 or len(translation) > 50:
                    response_text = "❌ Слишком длинное слово или перевод (максимум 50 символов)."
                else:
                    words_dict = user_data.get('words', {})
                    if word in words_dict:
                        response_text = f"⚠️ Слово '{word}' уже есть в словаре. Его перевод: {words_dict[word]['translation']}"
                    else:
                        words_dict[word] = {
                            'translation': translation,
                            'correct': 0,
                            'attempts': 0,
                            'last_attempt': None,
                            'streak': 0
                }
                user_data['words'] = words_dict
                user_data['state'] = 'main'
                session.commit()
                response_text = f"✅ Слово '{word}' с переводом '{translation}' добавлено!"
            except Exception:
                response_text = "❌ Ошибка при добавлении слова. Используй формат: слово:перевод"
        else:
            response_text = "❌ Неверный формат. Напиши: слово:перевод"
        user_data['state'] = 'main'
        session.commit()

    # Показать все слова с фильтрацией
    elif command == 'мои слова':
        words_dict = user_data.get('words', {})
        if words_dict:
            sort_by = user_data.get('sort_words', 'alphabetical')
            if sort_by == 'alphabetical':
                sorted_words = sorted(words_dict.items())
            elif sort_by == 'difficulty':
                sorted_words = sorted(words_dict.items(), key=lambda x: x[1]['correct'] / max(x[1]['attempts'], 1) if x[1]['attempts'] > 0 else 0)
            else:
                sorted_words = list(words_dict.items())

            words_list = [f"{w} — {d['translation']}" for w, d in sorted_words]
            response_text = f"📋 Твои слова ({len(words_list)}):\n" + "\n".join(words_list[:20])
            if len(words_list) > 20:
                response_text += f"\n... и ещё {len(words_list) - 20} слов. Покажи все командой 'все слова'."
        else:
            response_text = "📝 У тебя пока нет сохранённых слов. Добавь их командой 'новое слово'."

    # Статистика с детализацией
    elif command == 'статистика':
        words_dict = user_data.get('words', {})
        total = len(words_dict)
        attempts = sum(d['attempts'] for d in words_dict.values())
        correct = sum(d['correct'] for d in words_dict.values())
        accuracy = (correct / attempts * 100) if attempts > 0 else 0
        streak = max((d['streak'] for d in words_dict.values()), default=0)

        response_text = (
            f"📊 Статистика изучения:\n"
            f"Всего слов: {total}\n"
            f"Правильных ответов: {correct}\n"
            f"Всего попыток: {attempts}\n"
            f"Точность: {accuracy:.1f}%\n"
            f"Лучшая серия правильных ответов: {streak}\n\n"
            "Совет: старайся учить по 5–10 слов в день!"
        )

    # Совет по учёбе
    elif command == 'совет':
        words_dict = user_data.get('words', {})
        total = len(words_dict)
        if total == 0:
            response_text = "📚 Совет: начни с добавления первых 5–10 слов — это отличная отправная точка!"
        elif total < 10:
            response_text = "📚 Совет: добавь ещё несколько слов, чтобы тренировка была интереснее. Цель — 20–30 слов!"
        elif accuracy < 70:
            response_text = "📚 Совет: сосредоточься на словах с низкой точностью. Повторяй их чаще — и точность вырастет!"
        else:
            response_text = "📚 Отличный прогресс! Продолжай в том же духе — повторяй слова регулярно для лучшего запоминания."


    # Начало тренировки
    elif command == 'тест':
        words_dict = user_data.get('words', {})
        if not words_dict:
            response_text = "Сначала добавь слова командой 'новое слово'."
        else:
            test_mode = user_data.get('test_mode', 'en_ru')
            test_words = list(words_dict.keys())

            if test_mode == 'en_ru':
                current_word = random.choice(test_words)
                user_data['current_test_word'] = current_word
                user_data['state'] = 'answering_test'
                session.commit()
                response_text = f"❓ Как переводится слово '{current_word}'?"
            else:  # ru_en
                # Ищем слово с переводом, который выглядит как русское слово
                ru_words = [w for w, d in words_dict.items() if any(c in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя' for c in d['translation'])]
                if ru_words:
                    current_word_ru = random.choice(ru_words)
                    translation_en = words_dict[current_word_ru]['translation']
                    user_data['current_test_word'] = translation_en
                    user_data['expected_translation'] = current_word_ru
                    user_data['state'] = 'answering_test_ru_en'
                    session.commit()
            response_text = f"❓ Переведи на английский: '{current_word_ru}'?"
        else:
            response_text = "Недостаточно русских переводов для тренировки. Добавь слова с русскими переводами."

    # Ответ в режиме английский → русский
    elif user_data.get('state') == 'answering_test':
        current_word = user_data.get('current_test_word')
        words_dict = user_data.get('words', {})
        correct_translation = words_dict[current_word]['translation']
        user_answer = command.lower()

        words_dict[current_word]['attempts'] += 1
        if user_answer == correct_translation.lower():
            words_dict[current_word]['correct'] += 1
            words_dict[current_word]['streak'] += 1
            response_text = "✅ Правильно! Молодец!"
        else:
            words_dict[current_word]['streak'] = 0
            response_text = f"❌ Неверно. Правильный перевод: '{correct_translation}'"

        user_data['words'] = words_dict
        user_data['state'] = 'main'
        session.commit()

    # Ответ в режиме русский → английский
    elif user_data.get('state') == 'answering_test_ru_en':
        expected_translation = user_data.get('expected_translation')
        user_answer = command.lower().strip()
        words_dict = user_data.get('words', {})

        # Находим слово по ожидаемому переводу
        target_word = None
        for w, d in words_dict.items():
            if d['translation'].lower() == expected_translation.lower():
                target_word = w
                break

        if target_word:
            words_dict[target_word]['attempts'] += 1
            if user_answer == target_word.lower():
                words_dict[target_word]['correct'] += 1
                words_dict[target_word]['streak'] += 1
                response_text = "✅ Верно! Отлично!"
            else:
                words_dict[target_word]['streak'] = 0
                response_text = f"❌ Неправильно. Правильный ответ: '{target_word}'"

            user_data['words'] = words_dict
            user_data['state'] = 'main'
            session.commit()
        else:
            response_text = "❌ Ошибка системы. Попробуй начать тест заново."
            user_data['state'] = 'main'
            session.commit()

    # Удаление конкретного слова
    elif command.startswith('удалить слово '):
        word_to_delete = command.replace('удалить слово ', '').strip().lower()
        words_dict = user_data.get('words', {})
        if word_to_delete in words_dict:
            del words_dict[word_to_delete]
            user_data['words'] = words_dict
            session.commit()
            response_text = f"🗑️ Слово '{word_to_delete}' удалено."
        else:
            response_text = f"Слово '{word_to_delete}' не найдено."

    # Очистка всех слов
    elif command == 'очистить все':
        confirm = user_data.get('confirm_clear', False)
        if not confirm and command != 'да, точно очистить':
            user_data['confirm_clear'] = True
            session.commit()
            response_text = "⚠️ Ты уверен, что хочешь удалить ВСЕ слова? Скажи 'да, точно очистить' для подтверждения."
        else:
            user_data['words'] = {}
            user_data['confirm_clear'] = False
            user_data['state'] = 'main'
            session.commit()
            response_text = "🗑️ Все слова успешно удалены."

    # Неизвестная команда
    else:
        response_text = (
            "❌ Не поняла команду.\n"
            "Попробуй:\n"
            "- 'привет' — главное меню\n"
            "- 'новое слово' — добавить слово\n"
            "- 'мои слова' — посмотреть слова\n"
            "- 'тест' — тренировка\n"
            "- 'режим теста' — выбрать тип тренировки\n"
            "- 'статистика' — прогресс\n"
            "- 'совет' — рекомендация\n"
            "- 'помощь' — все команды"
        )

    bank_record.bank = user_data
    session.commit()

    response = {
        'response': {
            'text': response_text,
            'end_session': False
        },
        'version': req['version']
    }

    if suggested_actions:
        response['response']['buttons'] = suggested_actions


    return jsonify(response)



if __name__ == '__main__':
    app.run()
