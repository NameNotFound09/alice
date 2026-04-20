import os
import random
import json
import logging
from datetime import datetime

from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from sqlalchemy import orm

from data.db_session import global_init, create_session
from data.Banks import Bank
from data.Users import User
from forms import LoginForm, RegisterForm

app = Flask(__name__)
app.config['SECRET_KEY'] = 'enterprise_alice_dictionary_v5_final'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(BASE_DIR, 'db')
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, 'banks.sqlite')
global_init(db_path)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def get_default_data():
    return {
        "words": {},
        "stats": {
            "score": 0,
            "level": 1,
            "correct": 0,
            "wrong": 0,
            "streak": 0
        },
        "achievements": [],
        "categories": ["общие"],
        "history": []
    }


def get_safe_bank(entry):
    if not entry or not entry.bank:
        return get_default_data()
    if isinstance(entry.bank, str):
        try:
            return json.loads(entry.bank)
        except (json.JSONDecodeError, TypeError):
            return get_default_data()
    return entry.bank


def clean_text(text):
    if not text:
        return ""
    text = text.lower().strip()
    symbols = '.,!?;:-—"()[]{}'
    for char in symbols:
        text = text.replace(char, ' ')
    return " ".join(text.split())


def check_achievements(full_data):
    new_achs = []
    stats = full_data.get("stats", {})
    words_count = len(full_data.get("words", {}))

    if words_count >= 10 and "Новичок (10 слов)" not in full_data["achievements"]:
        new_achs.append("Новичок (10 слов)")
    if stats.get("score", 0) >= 100 and "Сотня!" not in full_data["achievements"]:
        new_achs.append("Сотня!")
    if stats.get("correct", 0) >= 50 and "Знаток" not in full_data["achievements"]:
        new_achs.append("Знаток")
    
    if new_achs:
        full_data["achievements"].extend(new_achs)
        return True, new_achs
    return False, []


@login_manager.user_loader
def load_user(user_id):
    db_sess = create_session()
    return db_sess.get(User, user_id)


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
        user = db_sess.query(User).filter(
            User.login == form.username.data
        ).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect("/main")
        flash('Неверные учетные данные', 'danger')
    return render_template('login.html', form=form)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect('/main')
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()
        if db_sess.query(User).filter(User.login == form.username.data).first():
            flash("Этот логин уже занят", "warning")
            return render_template('register.html', form=form)
        user = User(login=form.username.data)
        user.set_password(form.password.data)
        db_sess.add(user)
        db_sess.flush()
        new_bank = Bank(
            id=user.id,
            bank=get_default_data()
        )
        db_sess.add(new_bank)
        db_sess.commit()
        flash("Регистрация завершена!", "success")
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/")


@app.route('/main')
@login_required
def main():
    db_sess = create_session()
    bank_entry = db_sess.query(Bank).filter(Bank.id == current_user.id).first()
    data = get_safe_bank(bank_entry)
    return render_template(
        'main.html',
        words=data.get("words", {}),
        stats=data.get("stats", {}),
        achs=data.get("achievements", [])
    )


@app.route('/alice', methods=['POST'])
def alice_webhook():
    try:
        req = request.json
        user_id = req['session']['user_id']
        db_sess = create_session()
        bank_entry = db_sess.query(Bank).filter(Bank.alice_id == user_id).first()

        if not bank_entry:
            bank_entry = Bank(
                alice_id=user_id,
                bank=get_default_data()
            )
            db_sess.add(bank_entry)
            db_sess.commit()

        full_data = get_safe_bank(bank_entry)
        user_bank = full_data.get("words", {})
        stats = full_data.get("stats")

        raw_command = req['request']['command']
        command = clean_text(raw_command)
        state = req.get('state', {}).get('session', {})

        res = {
            "version": req['version'],
            "session": req['session'],
            "response": {"end_session": False, "buttons": []},
            "session_state": state
        }

        def build_response(text, tts=None, buttons=None, new_state=None):
            res["response"]["text"] = text
            if tts:
                res["response"]["tts"] = tts
            if buttons:
                res["response"]["buttons"] = [
                    {"title": b, "hide": True} for b in buttons
                ]
            else:
                res["response"]["buttons"] = [
                    {"title": "Тренировка", "hide": True},
                    {"title": "Добавить слово", "hide": True},
                    {"title": "Достижения", "hide": True},
                    {"title": "Статистика", "hide": True}
                ]
            if new_state is not None:
                res["session_state"] = new_state
            return jsonify(res)

        if any(x in command for x in ['стоп', 'выход', 'хватит', 'закрой']):
            return build_response(
                "До свидания! Жду новых тренировок.",
                tts="До встр+ечи! Возвращ+айся скор+ее.",
                new_state={}
            )

        if not command or req['session']['new']:
            welcome = (
                f"Рада видеть! В вашем словаре {len(user_bank)} слов. "
                f"Уровень: {stats.get('level')}. Что выберете?"
            )
            return build_response(
                welcome,
                buttons=["Учить", "Добавить", "Статистика", "Помощь"]
            )

        if any(x in command for x in ['помощь', 'умеешь', 'правила']):
            help_msg = (
                "Я — ваш тренажер. \n"
                "• Добавляйте: 'Добавь Кот — Cat'.\n"
                "• Учите: просто скажите 'Учить'.\n"
                "• Удаляйте: 'Удали слово Кот'.\n"
                "• Мои успехи: кнопка 'Статистика'."
            )
            return build_response(help_msg)

        if any(x in command for x in ['достижения', 'ачивки', 'награды']):
            achs = full_data.get("achievements", [])
            if not achs:
                return build_response("У вас пока нет наград. Начните учить слова!")
            msg = "Ваши награды: " + ", ".join(achs)
            return build_response(msg)

        if any(x in command for x in ['статистика', 'прогресс', 'счет']):
            msg = (
                f"Ваш прогресс:\n"
                f"Очки: {stats.get('score')}\n"
                f"Уровень: {stats.get('level')}\n"
                f"Верно: {stats.get('correct')}\n"
                f"Ошибок: {stats.get('wrong')}"
            )
            return build_response(msg)

        if command.startswith(('удали', 'сотри', 'забудь')):
            target = command.replace('удали', '').replace(
                'сотри', '').replace('забудь', '').replace('слово', '').strip()
            if target in user_bank:
                del user_bank[target]
                full_data["words"] = user_bank
                bank_entry.bank = full_data
                orm.attributes.flag_modified(bank_entry, "bank")
                db_sess.commit()
                return build_response(f"Слово '{target}' удалено.")
            return build_response(f"Слова '{target}' нет в списке.")

        if command in ['добавить', 'добавить слово', 'новое слово']:
            return build_response(
                "Какое слово запишем? Сначала назовите на русском.",
                new_state={"action": "add_1"}
            )

        if state.get('action') == "add_1":
            return build_response(
                f"Запомнила: '{raw_command}'. Какой перевод?",
                new_state={"action": "add_2", "tmp_w": raw_command}
            )

        if state.get('action') == "add_2":
            word = state.get('tmp_w')
            user_bank[word] = raw_command
            full_data["words"] = user_bank
            bank_entry.bank = full_data
            orm.attributes.flag_modified(bank_entry, "bank")
            db_sess.commit()
            return build_response(
                f"Готово! '{word}' теперь в словаре.",
                new_state={},
                buttons=["Учить", "Еще слово"]
            )

        for sep in ['—', '-', 'тире', 'это']:
            if sep in raw_command and 'добавь' in command:
                parts = raw_command.lower().replace(
                    'добавь', '').replace('слово', '').split(sep)
                if len(parts) >= 2:
                    w, t = parts[0].strip(), parts[1].strip()
                    user_bank[w] = t
                    full_data["words"] = user_bank
                    bank_entry.bank = full_data
                    orm.attributes.flag_modified(bank_entry, "bank")
                    db_sess.commit()
                    return build_response(f"Добавила: {w} - {t}.")

        if command in ['учить', 'тренировка', 'старт', 'играть'] or state.get('cur'):
            words_list = list(user_bank.keys())
            if len(words_list) < 2:
                return build_response("Нужно добавить хотя бы 2 слова для теста.")

            current_q = state.get('cur')
            if not current_q:
                new_q = random.choice(words_list)
                return build_response(
                    f"Как переводится '{new_q}'?",
                    new_state={"cur": new_q}
                )

            correct = user_bank.get(current_q, "").lower().strip()
            if command == clean_text(correct):
                stats['score'] += 10
                stats['correct'] += 1
                stats['streak'] += 1

                if stats['score'] >= stats['level'] * 100:
                    stats['level'] += 1
                    msg, sound = "Новый уровень! ", "game-win-1"
                else:
                    msg, sound = "Верно! ", "game-ping-1"

                updated, new_achs = check_achievements(full_data)
                if updated:
                    msg += f"Получена награда: {', '.join(new_achs)}! "

                full_data['stats'] = stats
                bank_entry.bank = full_data
                orm.attributes.flag_modified(bank_entry, "bank")
                db_sess.commit()

                next_q = random.choice([w for w in words_list if w != current_q])
                return build_response(
                    f"{msg}Дальше: '{next_q}'?",
                    tts=f"<speaker audio=\"alice-sounds-{sound}.opus\"> {msg} "
                        f"Следующее: {next_q}?",
                    new_state={"cur": next_q}
                )

            if any(x in command for x in ['не знаю', 'сдаюсь', 'пропусти']):
                stats['wrong'] += 1
                stats['streak'] = 0
                next_q = random.choice([w for w in words_list if w != current_q])
                return build_response(
                    f"'{current_q}' — это '{correct}'. Дальше: '{next_q}'?",
                    new_state={"cur": next_q}
                )

            return build_response(
                f"Нет. Попробуйте еще раз: '{current_q}'?",
                tts=f"<speaker audio=\"alice-sounds-game-loss-1.opus\"> "
                    f"Попр+обуй ещ+е раз. {current_q}?",
                new_state={"cur": current_q},
                buttons=["Сдаюсь", "Подсказка"]
            )

        if command == 'подсказка' and state.get('cur'):
            word = state.get('cur')
            correct = user_bank.get(word, "")
            hint = f"{correct[0]}{'*' * (len(correct) - 1)}"
            return build_response(f"Первая буква: {hint}", new_state=state)

        return build_response("Не совсем поняла вас. Попробуйте нажать 'Помощь'.")

    except Exception as e:
        logger.error(f"Critical error in Alice Webhook: {e}", exc_info=True)
        return jsonify({
            "version": "1.0",
            "response": {
                "text": "Произошла системная ошибка. Мы уже чиним её!",
                "end_session": False
            }
        })


if __name__ == '__main__':
    server_port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=server_port)