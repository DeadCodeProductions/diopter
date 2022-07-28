from __future__ import annotations

import hashlib
import zlib
from copy import deepcopy
from typing import Any, Optional

import sqlalchemy
import sqlalchemy.types as types
from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, declarative_base, relationship
from sqlalchemy.schema import FetchedValue

Base = declarative_base()


def compress(s: str) -> bytes:
    return zlib.compress(s.encode("utf-8"), level=9)


def decompress(s: bytes) -> str:
    return zlib.decompress(s).decode("utf-8")


class CompressedString(types.TypeDecorator[str]):

    impl = types.BLOB
    # cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[bytes]:
        if value is None:
            return None
        return compress(value)

    def process_result_value(self, value: bytes, dialect: Any) -> str:
        return decompress(value)


class HashableStringList(list[str]):
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HashableStringList) or len(self) != len(other):
            return False
        for a, b in zip(sorted(self), sorted(other)):
            if a != b:
                return False
        return True

    def __hash__(self) -> int:  # type: ignore
        tmp = sorted(self)
        res = hash("||".join(tmp if not self.is_empty() else ["||EMPTY||"]))
        return res

    def is_empty(self) -> bool:
        return len(self) == 0


class CompressedStringList(types.TypeDecorator[HashableStringList]):

    impl = types.BLOB

    # cache_ok = True

    def process_bind_param(
        self, value: Optional[HashableStringList], dialect: Any
    ) -> Optional[bytes]:
        if value is None:
            return None
        if not value:
            return compress("||EMPTY||")
        return compress("||".join(sorted(value)))

    def process_result_value(self, value: bytes, dialect: Any) -> HashableStringList:
        res = decompress(value)
        if res == "||EMPTY||":
            return HashableStringList()
        return HashableStringList(res.split("||"))


class _Sequence(Base):
    __tablename__ = "sequence"
    key = Column(Integer(), primary_key=True)


class Code(Base):
    __tablename__ = "code"

    id: Mapped[str] = Column(String(40), primary_key=True, nullable=False)
    code: Mapped[str] = Column(CompressedString(), nullable=False)

    def __repr__(self) -> str:
        return f"{self.id!r} {self.code!r}"

    @staticmethod
    def make(code: str) -> Code:
        # TODO: make better constructor
        code_sha1 = hashlib.sha1(code.encode("utf-8")).hexdigest()
        return Code(id=code_sha1, code=code)


Trigger = sqlalchemy.DDL(
    """
CREATE TRIGGER IF NOT EXISTS auto_increment_trigger
AFTER INSERT ON compiler_setting
WHEN new.id IS NULL
BEGIN
    INSERT INTO sequence VALUES (NULL);
    UPDATE compiler_setting 
    SET id = (SELECT MAX(key) FROM sequence)
    WHERE 
    compiler_name = new.compiler_name AND
    rev == new.rev AND
    opt_level == new.opt_level AND
    additional_flags == new.additional_flags;
END;
"""
)


class CompilerSetting(Base):
    __tablename__ = "compiler_setting"

    # id = Column(
    #    Integer(), sqlalchemy.Sequence("compiler_id_seq"), unique=True
    # )  # DuckDB
    id = Column(Integer(), unique=True)  # Trigger
    # id = Column(Integer(), server_default=(sqlalchemy.sql.functions.max(_Sequence.key)+1), unique=True)
    # id = Column(BigInteger().with_variant(Integer, "sqlite"), autoincrement=True, unique=True)
    compiler_name: Mapped[str] = Column(String(10), primary_key=True)
    rev: Mapped[str] = Column(String(40), primary_key=True)
    opt_level: Mapped[str] = Column(String(1), primary_key=True)
    additional_flags: Mapped[HashableStringList] = Column(
        CompressedStringList(), primary_key=True
    )

    def __repr__(self) -> str:
        return f"CSetting({self.compiler_name} {self.rev} {self.opt_level} {self.additional_flags})"

    def get_flag_string(self) -> str:
        return f"-O{self.opt_level} " + " ".join(self.additional_flags)

    def copy_override(
        self,
        name: Optional[str] = None,
        rev: Optional[str] = None,
        opt_level: Optional[str] = None,
        additional_flags: Optional[HashableStringList] = None,
    ) -> CompilerSetting:

        cleared_name = name if name else deepcopy(self.compiler_name)
        cleared_rev = rev if rev else deepcopy(self.rev)
        cleared_opt_level = opt_level if opt_level else deepcopy(self.opt_level)
        cleared_additional_flags = (
            additional_flags if additional_flags else deepcopy(self.additional_flags)
        )

        return CompilerSetting(
            compiler_name=cleared_name,
            rev=cleared_rev,
            opt_level=cleared_opt_level,
            additional_flags=cleared_additional_flags,
        )
