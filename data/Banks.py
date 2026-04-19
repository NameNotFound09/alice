import sqlalchemy
from .db_session import SqlAlchemyBase


class Bank(SqlAlchemyBase):
    __tablename__ = 'banks'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey('users.id'), primary_key=True)
    bank = sqlalchemy.Column(sqlalchemy.JSON)
    alice_id = sqlalchemy.Column(sqlalchemy.String, nullable=True, unique=True)