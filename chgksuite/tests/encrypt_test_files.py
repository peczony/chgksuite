"""Utility to encrypt/decrypt test files for the test suite.

Uses simple XOR encryption - sufficient to prevent casual access to test files.

Usage:
    python encrypt_test_files.py generate-password
        Generate a new password and save to tests_password.txt

    python encrypt_test_files.py encrypt <file1> [file2] ...
        Encrypt files (creates .encrypted versions)

    python encrypt_test_files.py decrypt <file.encrypted> [file2.encrypted] ...
        Decrypt files (saves without .encrypted suffix)
"""

import hashlib
import os
import secrets
import sys

PASSWORD_FILE = os.path.join(os.path.dirname(__file__), "tests_password.txt")


def xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data with repeating key."""
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def get_key_from_password(password: str) -> bytes:
    """Derive a key from password using SHA-256."""
    return hashlib.sha256(password.encode()).digest()


def encrypt_data(data: bytes, password: str) -> bytes:
    """Encrypt data with password."""
    key = get_key_from_password(password)
    return xor_bytes(data, key)


def decrypt_data(data: bytes, password: str) -> bytes:
    """Decrypt data with password (XOR is symmetric)."""
    return encrypt_data(data, password)


def encrypt_file(filepath: str, password: str) -> str:
    """Encrypt a file, return path to encrypted file.

    For .canon files, produces .encrypted.canon (not .canon.encrypted)
    to match the test suite naming convention.
    """
    with open(filepath, "rb") as f:
        encrypted = encrypt_data(f.read(), password)
    if filepath.endswith(".canon"):
        # file.docx.canon -> file.docx.encrypted.canon
        out_path = filepath[:-6] + ".encrypted.canon"
    else:
        out_path = filepath + ".encrypted"
    with open(out_path, "wb") as f:
        f.write(encrypted)
    return out_path


def decrypt_file(filepath: str, password: str) -> bytes:
    """Decrypt a file, return decrypted content."""
    with open(filepath, "rb") as f:
        return decrypt_data(f.read(), password)


def generate_password() -> str:
    """Generate a random password."""
    return secrets.token_urlsafe(32)


def read_password() -> str:
    """Read password from file."""
    if not os.path.exists(PASSWORD_FILE):
        print(f"Error: Password file not found: {PASSWORD_FILE}", file=sys.stderr)
        print(
            "Run 'python encrypt_test_files.py generate-password' first",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(PASSWORD_FILE, "r") as f:
        return f.read().strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "generate-password":
        if os.path.exists(PASSWORD_FILE):
            print(f"Warning: {PASSWORD_FILE} already exists!", file=sys.stderr)
            response = input("Overwrite? (y/N): ")
            if response.lower() != "y":
                print("Aborted.")
                sys.exit(0)
        password = generate_password()
        with open(PASSWORD_FILE, "w") as f:
            f.write(password)
        print(f"Password saved to {PASSWORD_FILE}")
        print(f"Password: {password}")
        print("\nShare this password securely with trusted developers.")

    elif command == "encrypt":
        if len(sys.argv) < 3:
            print(
                "Usage: python encrypt_test_files.py encrypt <file1> [file2] ...",
                file=sys.stderr,
            )
            sys.exit(1)
        password = read_password()
        for filepath in sys.argv[2:]:
            out_path = encrypt_file(filepath, password)
            print(f"Encrypted: {filepath} -> {out_path}")

    elif command == "decrypt":
        if len(sys.argv) < 3:
            print(
                "Usage: python encrypt_test_files.py decrypt <file.encrypted> [file2.encrypted] ...",
                file=sys.stderr,
            )
            sys.exit(1)
        password = read_password()
        for filepath in sys.argv[2:]:
            content = decrypt_file(filepath, password)
            if filepath.endswith(".encrypted"):
                out_path = filepath[:-10]  # Remove .encrypted
                with open(out_path, "wb") as f:
                    f.write(content)
                print(f"Decrypted: {filepath} -> {out_path}")
            else:
                sys.stdout.buffer.write(content)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
