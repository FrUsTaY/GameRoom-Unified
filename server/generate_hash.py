#!/usr/bin/env python3
"""
CLI tool for generating Argon2id password hashes for GameRoom Web Authentication.
Usage:
    python generate_hash.py
    python generate_hash.py <your_password>
"""
import sys
import getpass

try:
    from argon2 import PasswordHasher
except ImportError:
    print("Error: argon2-cffi is not installed.")
    print("Please install dependencies: pip install argon2-cffi")
    sys.exit(1)

def main():
    print("=" * 60)
    print("  GAME-ROOM // Argon2id Password Hash Generator")
    print("=" * 60)

    if len(sys.argv) > 1:
        pwd = sys.argv[1]
    else:
        try:
            pwd = getpass.getpass("Введите новый пароль для GameRoom Web: ")
            if not pwd:
                print("Ошибка: пароль не может быть пустым.")
                sys.exit(1)
            pwd_confirm = getpass.getpass("Повторите пароль для проверки: ")
            if pwd != pwd_confirm:
                print("Ошибка: пароли не совпадают!")
                sys.exit(1)
        except (KeyboardInterrupt, EOFError):
            print("\nОтменено.")
            sys.exit(0)

    hasher = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16
    )

    print("\nГенерация хэша Argon2id...")
    password_hash = hasher.hash(pwd)

    print("\n" + "=" * 60)
    print("Хэш успешно сгенерирован!")
    print("=" * 60)
    print(f"\nДобавьте в ваш файл .env на сервере:\n")
    print(f"GAME_ROOM_WEB_PASSWORD_HASH='{password_hash}'\n")
    print("=" * 60)

if __name__ == "__main__":
    main()
