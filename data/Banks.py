import sqlalchemy
from .db_session import SqlAlchemyBase

class Bank(SqlAlchemyBase):
    __tablename__ = 'banks'

    # Убедись, что тут есть primary_key и autoincrement
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    
    # Это поле для связи с сайтом
    user_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True)
    
    # Это поле для Алисы
    alice_id = sqlalchemy.Column(sqlalchemy.String, nullable=True, unique=True)
    
    bank = sqlalchemy.Column(sqlalchemy.JSON, nullable=True)