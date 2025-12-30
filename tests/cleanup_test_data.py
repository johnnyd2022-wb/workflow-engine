#!/usr/bin/env python3
"""Cleanup script to remove test data created by test_multi_tenant_api.py"""

import sys

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository


def cleanup_test_data():
    """Remove test organisations and users"""
    db = db_session()
    try:
        org_repo = OrganisationRepository(db)
        user_repo = UserRepository(db)

        # Test data identifiers
        test_org_names = ["Test Company", "Test Company Updated"]
        test_emails = ["admin@test.com", "member@test.com"]

        print("🧹 Cleaning up test data...\n")

        # Import models for direct deletion
        from app.core.db.models.audit_log import AuditLog

        # Find and delete test organisations
        deleted_orgs = 0
        deleted_users = 0  # Track users deleted as part of org deletion
        for org_name in test_org_names:
            org = org_repo.get_org_by_name(org_name)
            if org:
                print(f"  Found organisation: {org_name} (ID: {org.id})")

                # Delete audit logs for this org first (to avoid FK constraint issues)
                audit_logs = db.query(AuditLog).filter(AuditLog.org_id == org.id).all()
                if audit_logs:
                    print(f"    Deleting {len(audit_logs)} audit log entries...")
                    for log in audit_logs:
                        db.delete(log)
                    db.commit()

                # Delete all users in this org (hard delete)
                users = user_repo.list_users_for_org(org.id, active_only=False)
                for user in users:
                    print(f"    Hard deleting user: {user.email}")
                    # Hard delete: actually remove from database
                    db.delete(user)
                    deleted_users += 1  # Count users deleted with org
                db.commit()

                # Hard delete the org
                print(f"    Hard deleting organisation: {org_name}")
                db.delete(org)
                db.commit()
                print(f"  ✅ Deleted organisation: {org_name}\n")
                deleted_orgs += 1

        # Also check for test users by email (in case org was already deleted)
        for email in test_emails:
            user = user_repo.get_user_by_email(email)
            if user:
                print(f"  Found orphaned user: {email} (ID: {user.id})")

                # Delete audit logs for this user
                audit_logs = db.query(AuditLog).filter(AuditLog.user_id == user.id).all()
                if audit_logs:
                    print(f"    Deleting {len(audit_logs)} audit log entries...")
                    for log in audit_logs:
                        db.delete(log)
                    db.commit()

                # Hard delete: actually remove from database
                db.delete(user)
                db.commit()
                print(f"  ✅ Deleted user: {email}\n")
                deleted_users += 1

        if deleted_orgs == 0 and deleted_users == 0:
            print("  ℹ️  No test data found to clean up")
        else:
            print(f"✅ Cleanup complete! Deleted {deleted_orgs} organisation(s) and {deleted_users} user(s)")

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        db.rollback()
        sys.exit(1)
    # Don't close session - let middleware handle it if called from Flask context
    # But since this is a standalone script, we should close it
    finally:
        db.close()


def list_test_data():
    """List all test organisations and users"""
    db = db_session()
    try:
        org_repo = OrganisationRepository(db)
        user_repo = UserRepository(db)

        test_org_names = ["Test Company", "Test Company Updated"]
        test_emails = ["admin@test.com", "member@test.com"]

        print("📋 Test Data Inventory:\n")

        # List test organisations
        found_orgs = []
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

        # List orphaned test users
        found_users = []
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

        if not found_orgs and not found_users:
            print("  ℹ️  No test data found")

    except Exception as e:
        print(f"❌ Error listing test data: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_test_data()
    else:
        cleanup_test_data()
