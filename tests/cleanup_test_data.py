#!/usr/bin/env python3
"""Cleanup script to remove test data created by all tests in the tests/ directory"""

import sys

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository


def _delete_user_related_data(db, user_id):
    """Delete all data related to a user (backup codes, trusted devices, audit logs)"""
    from app.core.db.models.audit_log import AuditLog
    from app.core.db.models.trusted_device import TrustedDevice
    from app.core.db.models.two_factor_backup_code import TwoFactorBackupCode

    # Delete backup codes
    backup_codes = db.query(TwoFactorBackupCode).filter(TwoFactorBackupCode.user_id == user_id).all()
    if backup_codes:
        for code in backup_codes:
            db.delete(code)
        db.commit()

    # Delete trusted devices
    trusted_devices = db.query(TrustedDevice).filter(TrustedDevice.user_id == user_id).all()
    if trusted_devices:
        for device in trusted_devices:
            db.delete(device)
        db.commit()

    # Delete audit logs
    audit_logs = db.query(AuditLog).filter(AuditLog.user_id == user_id).all()
    if audit_logs:
        for log in audit_logs:
            db.delete(log)
        db.commit()


def _delete_org_related_data(db, org_id):
    """Delete all data related to an organisation (audit logs)"""
    from app.core.db.models.audit_log import AuditLog

    # Delete audit logs for this org
    audit_logs = db.query(AuditLog).filter(AuditLog.org_id == org_id).all()
    if audit_logs:
        for log in audit_logs:
            db.delete(log)
        db.commit()


def cleanup_test_data():
    """Remove test organisations and users (both hardcoded and dynamic test data)"""
    db = db_session()
    try:
        org_repo = OrganisationRepository(db)
        user_repo = UserRepository(db)

        # Hardcoded test data identifiers (from test_multi_tenant_api.py)
        test_org_names = ["Test Company", "Test Company Updated"]
        test_emails = ["admin@test.com", "member@test.com"]

        print("🧹 Cleaning up test data...\n")

        deleted_orgs = 0
        deleted_users = 0

        # ==========================================
        # Clean up hardcoded test data
        # ==========================================
        print("📋 Cleaning up hardcoded test data...\n")
        for org_name in test_org_names:
            org = org_repo.get_org_by_name(org_name)
            if org:
                print(f"  Found organisation: {org_name} (ID: {org.id})")

                # Delete org-related data
                _delete_org_related_data(db, org.id)

                # Delete all users in this org (hard delete)
                users = user_repo.list_users_for_org(org.id, active_only=False)
                for user in users:
                    print(f"    Hard deleting user: {user.email}")
                    # Delete user-related data first
                    _delete_user_related_data(db, user.id)
                    # Then delete the user
                    db.delete(user)
                    deleted_users += 1
                db.commit()

                # Hard delete the org
                print(f"    Hard deleting organisation: {org_name}")
                db.delete(org)
                db.commit()
                print(f"  ✅ Deleted organisation: {org_name}\n")
                deleted_orgs += 1

        # Also check for hardcoded test users by email (in case org was already deleted)
        for email in test_emails:
            user = user_repo.get_user_by_email(email)
            if user:
                print(f"  Found orphaned user: {email} (ID: {user.id})")
                # Delete user-related data first
                _delete_user_related_data(db, user.id)
                # Then delete the user
                db.delete(user)
                db.commit()
                print(f"  ✅ Deleted user: {email}\n")
                deleted_users += 1

        # ==========================================
        # Clean up dynamic test data (from 2FA tests)
        # ==========================================
        print("\n📋 Cleaning up dynamic test data (TestOrg_* and test_*@test.com)...\n")

        # Find all orgs matching TestOrg_ pattern
        from app.core.db.models.user import User

        all_orgs = org_repo.list_orgs()
        test_orgs = [org for org in all_orgs if org.name.startswith("TestOrg_")]

        for org in test_orgs:
            print(f"  Found test organisation: {org.name} (ID: {org.id})")

            # Delete org-related data
            _delete_org_related_data(db, org.id)

            # Delete all users in this org
            users = user_repo.list_users_for_org(org.id, active_only=False)
            for user in users:
                print(f"    Hard deleting user: {user.email}")
                # Delete user-related data first
                _delete_user_related_data(db, user.id)
                # Then delete the user
                db.delete(user)
                deleted_users += 1
            db.commit()

            # Delete org
            print(f"    Hard deleting organisation: {org.name}")
            db.delete(org)
            db.commit()
            print(f"  ✅ Deleted organisation: {org.name}\n")
            deleted_orgs += 1

        # Also find orphaned test users (emails matching test_*@test.com pattern)
        all_users = db.query(User).all()
        test_users = [u for u in all_users if u.email.startswith("test_") and u.email.endswith("@test.com")]

        for user in test_users:
            # Check if user's org was already deleted or is a test org
            org = org_repo.get_org_by_id(user.org_id) if user.org_id else None
            if not org or org.name.startswith("TestOrg_"):
                print(f"  Found orphaned test user: {user.email} (ID: {user.id})")
                # Delete user-related data first
                _delete_user_related_data(db, user.id)
                # Then delete the user
                db.delete(user)
                db.commit()
                print(f"  ✅ Deleted user: {user.email}\n")
                deleted_users += 1

        # ==========================================
        # Summary
        # ==========================================
        if deleted_orgs == 0 and deleted_users == 0:
            print("  ℹ️  No test data found to clean up")
        else:
            print(f"\n✅ Cleanup complete! Deleted {deleted_orgs} organisation(s) and {deleted_users} user(s)")

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        import traceback

        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


def list_test_data():
    """List all test organisations and users (both hardcoded and dynamic)"""
    db = db_session()
    try:
        org_repo = OrganisationRepository(db)
        user_repo = UserRepository(db)
        from app.core.db.models.user import User

        # Hardcoded test data
        test_org_names = ["Test Company", "Test Company Updated"]
        test_emails = ["admin@test.com", "member@test.com"]

        print("📋 Test Data Inventory:\n")

        found_orgs = []
        found_users = []

        # List hardcoded test organisations
        print("📌 Hardcoded test data:\n")
        for org_name in test_org_names:
            org = org_repo.get_org_by_name(org_name)
            if org:
                found_orgs.append(org)
                print(f"  Organisation: {org.name}")
                print(f"    ID: {org.id}")
                print(f"    Status: {org.status.value}")
                users = user_repo.list_users_for_org(org.id, active_only=False)
                print(f"    Users: {len(users)}")
                for user in users:
                    print(f"      - {user.email} ({user.role.value}, active: {user.is_active})")
                print()

        # List hardcoded orphaned test users
        for email in test_emails:
            user = user_repo.get_user_by_email(email)
            if user:
                # Check if user's org is in our test orgs list
                org = org_repo.get_org_by_id(user.org_id)
                if not org or org.name not in test_org_names:
                    found_users.append(user)
                    print(f"  Orphaned User: {user.email}")
                    print(f"    ID: {user.id}")
                    print(f"    Org ID: {user.org_id}")
                    print(f"    Role: {user.role.value}")
                    print(f"    Active: {user.is_active}")
                    print()

        # List dynamic test data (TestOrg_* pattern)
        print("\n📌 Dynamic test data (TestOrg_*):\n")
        all_orgs = org_repo.list_orgs()
        test_orgs = [org for org in all_orgs if org.name.startswith("TestOrg_")]

        for org in test_orgs:
            found_orgs.append(org)
            print(f"  Organisation: {org.name}")
            print(f"    ID: {org.id}")
            print(f"    Status: {org.status.value}")
            users = user_repo.list_users_for_org(org.id, active_only=False)
            print(f"    Users: {len(users)}")
            for user in users:
                print(f"      - {user.email} ({user.role.value}, active: {user.is_active})")
            print()

        # List dynamic orphaned test users (test_*@test.com pattern)
        all_users = db.query(User).all()
        test_users = [u for u in all_users if u.email.startswith("test_") and u.email.endswith("@test.com")]

        for user in test_users:
            org = org_repo.get_org_by_id(user.org_id) if user.org_id else None
            if not org or org.name.startswith("TestOrg_"):
                found_users.append(user)
                print(f"  Orphaned Test User: {user.email}")
                print(f"    ID: {user.id}")
                print(f"    Org ID: {user.org_id}")
                print(f"    Role: {user.role.value}")
                print(f"    Active: {user.is_active}")
                print()

        if not found_orgs and not found_users:
            print("  ℹ️  No test data found")
        else:
            print(f"\n📊 Summary: {len(found_orgs)} organisation(s), {len(found_users)} orphaned user(s)")

    except Exception as e:
        print(f"❌ Error listing test data: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_test_data()
    else:
        cleanup_test_data()
