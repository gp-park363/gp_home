"""관리자 계정 만들기 (첫 계정은 이 명령으로, 이후에는 관리자 화면 '계정'에서).

    make create-admin                                   # 대화형
    python -m scripts.create_user --email a@b.kr --name 홍길동 --role admin

같은 이메일이 있으면 비밀번호·권한을 다시 정하고 계정을 켭니다 (비밀번호 분실 복구용).
"""

import argparse
import getpass

from sqlalchemy import select

from app.content import ROLES
from app.db import SessionLocal
from app.models import User
from app.services import auth


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--email")
    ap.add_argument("--name")
    ap.add_argument("--role", choices=list(ROLES), default="admin")
    args = ap.parse_args()

    email = auth.normalize_email(args.email or input("이메일(로그인 ID): "))
    name = (args.name or input("이름: ")).strip()
    while True:
        password = getpass.getpass("비밀번호: ")
        problem = auth.password_problem(password, getpass.getpass("비밀번호 확인: "))
        if not problem:
            break
        print(problem)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name or email, role=args.role, password_hash="")
            db.add(user)
            db.flush()
            action = "만들었습니다"
        else:
            action = "다시 설정했습니다"
            user.is_active = True
            user.role = args.role
            if name:
                user.name = name
        auth.set_password(user, password)
        db.commit()
    print(f"{email} ({ROLES[args.role]}) 계정을 {action}.")


if __name__ == "__main__":
    main()
