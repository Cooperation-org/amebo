#!/usr/bin/env python3
"""
Test script for Task 2: Auth Utils JWT Fix Verification
Tests that JWT_SECRET_KEY loads correctly from .env file
"""

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}{msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}{msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW} {msg}{Colors.END}")

def test_env_file_exists():
    """Test 1: .env file exists"""
    print("\n" + "="*70)
    print("TEST 1: .env File Exists")
    print("="*70)

    env_path = Path(__file__).parent / '.env'

    if env_path.exists():
        print_success(f".env file found at: {env_path}")
        return True
    else:
        print_error(f".env file not found at: {env_path}")
        print_info("Create .env file with JWT_SECRET_KEY")
        return False

def test_jwt_secret_in_env():
    """Test 2: JWT_SECRET_KEY exists in .env"""
    print("\n" + "="*70)
    print("TEST 2: JWT_SECRET_KEY in .env")
    print("="*70)

    env_path = Path(__file__).parent / '.env'

    try:
        with open(env_path) as f:
            content = f.read()

        if 'JWT_SECRET_KEY' in content:
            # Check if it has a value
            for line in content.split('\n'):
                if line.startswith('JWT_SECRET_KEY') and '=' in line:
                    key = line.split('=', 1)[1].strip()
                    if key and key != 'your-secret-key-here':
                        print_success("JWT_SECRET_KEY is set in .env")
                        print_info(f"Key length: {len(key)} characters")
                        return True
                    else:
                        print_warning("JWT_SECRET_KEY exists but has no value")
                        return False

            print_warning("JWT_SECRET_KEY found but not properly formatted")
            return False
        else:
            print_error("JWT_SECRET_KEY not found in .env")
            print_info("Add: JWT_SECRET_KEY=your-secret-key")
            return False

    except Exception as e:
        print_error(f"Error reading .env file: {e}")
        return False

def test_auth_utils_imports():
    """Test 3: auth_utils module imports without errors"""
    print("\n" + "="*70)
    print("TEST 3: Auth Utils Imports")
    print("="*70)

    try:
        # This will trigger load_dotenv() in auth_utils
        from src.api import auth_utils
        print_success("auth_utils imported successfully")
        return True
    except RuntimeError as e:
        if "JWT_SECRET_KEY environment variable is required" in str(e):
            print_error("JWT_SECRET_KEY not loaded from .env")
            print_info("Error: " + str(e))
            return False
        else:
            print_error(f"Unexpected RuntimeError: {e}")
            return False
    except Exception as e:
        print_error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_jwt_secret_accessible():
    """Test 4: JWT_SECRET_KEY is accessible in auth_utils"""
    print("\n" + "="*70)
    print("TEST 4: JWT_SECRET_KEY Accessible")
    print("="*70)

    try:
        from src.api import auth_utils

        if hasattr(auth_utils, 'SECRET_KEY') and auth_utils.SECRET_KEY:
            print_success("SECRET_KEY is accessible")
            print_info(f"Key type: {type(auth_utils.SECRET_KEY).__name__}")
            print_info(f"Key length: {len(auth_utils.SECRET_KEY)} characters")

            # Verify it's a string
            if isinstance(auth_utils.SECRET_KEY, str):
                print_success("SECRET_KEY is a string (correct type)")
                return True
            else:
                print_error(f"SECRET_KEY has wrong type: {type(auth_utils.SECRET_KEY)}")
                return False
        else:
            print_error("SECRET_KEY not found or empty")
            return False

    except Exception as e:
        print_error(f"Failed to access SECRET_KEY: {e}")
        return False

def test_jwt_functions():
    """Test 5: JWT functions work correctly"""
    print("\n" + "="*70)
    print("TEST 5: JWT Functions Work")
    print("="*70)

    try:
        from src.api.auth_utils import create_access_token, decode_token

        # Create test token
        test_data = {
            "user_id": 1,
            "org_id": 1,
            "email": "test@example.com",
            "role": "admin"
        }

        print_info("Creating test JWT token...")
        token = create_access_token(test_data)
        print_success("Token created successfully")
        print_info(f"Token length: {len(token)} characters")

        # Decode token
        print_info("Decoding test JWT token...")
        decoded = decode_token(token)
        print_success("Token decoded successfully")

        # Verify data
        if decoded.get("user_id") == test_data["user_id"]:
            print_success("Token data verified (user_id matches)")
        else:
            print_error("Token data mismatch")
            return False

        if decoded.get("type") == "access":
            print_success("Token type verified (access token)")
        else:
            print_error("Token type incorrect")
            return False

        return True

    except Exception as e:
        print_error(f"JWT functions failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_password_functions():
    """Test 6: Password hashing works"""
    print("\n" + "="*70)
    print("TEST 6: Password Hashing Works")
    print("="*70)

    try:
        from src.api.auth_utils import hash_password, verify_password

        test_password = "test_password_123"

        print_info("Hashing test password...")
        hashed = hash_password(test_password)
        print_success("Password hashed successfully")
        print_info(f"Hash length: {len(hashed)} characters")

        print_info("Verifying correct password...")
        if verify_password(test_password, hashed):
            print_success("Password verification works (correct password)")
        else:
            print_error("Password verification failed (should match)")
            return False

        print_info("Verifying wrong password...")
        if not verify_password("wrong_password", hashed):
            print_success("Password verification works (wrong password rejected)")
        else:
            print_error("Password verification failed (should reject)")
            return False

        return True

    except Exception as e:
        print_error(f"Password functions failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests():
    """Run all verification tests"""
    print("\n" + "🔍 TASK 2 VERIFICATION: Auth Utils JWT Fix")
    print("="*70)
    print("Testing JWT environment variable loading...\n")

    results = {}

    # Run tests
    results['env_file'] = test_env_file_exists()
    results['jwt_in_env'] = test_jwt_secret_in_env()
    results['imports'] = test_auth_utils_imports()
    results['secret_accessible'] = test_jwt_secret_accessible()
    results['jwt_functions'] = test_jwt_functions()
    results['password_functions'] = test_password_functions()

    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"{status} - {test_name}")

    print("\n" + "="*70)
    if passed == total:
        print_success(f"ALL TESTS PASSED ({passed}/{total})")
        print_success("✨ Task 2 is READY for PR!")
    else:
        print_error(f"SOME TESTS FAILED ({passed}/{total} passed)")
        print_info("Fix failures before creating PR")
    print("="*70)

    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
