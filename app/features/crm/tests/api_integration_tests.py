"""
Real API integration tests for CRM alias endpoints.
These tests make actual HTTP requests to the Flask API endpoints.
"""

import os
import sys
import unittest
from datetime import datetime

# Add the project root to Python path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../.."))

# Import Flask app and initialize
try:
    from app import app
    from app.initialize import db_conn
except ImportError as e:
    print(f"Could not import app or db_conn: {e}")
    print("Make sure you're running from the project root directory")


class TestAliasAPIRealEndpoints(unittest.TestCase):
    """Real API integration tests using HTTP requests"""

    def setUp(self):
        """Set up test fixtures with real database connection"""
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()

        # Create test customer data with timestamps for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.test_customer = f"APITest_Customer_{timestamp}"
        self.test_alias_1 = f"APITest_Alias1_{timestamp}"
        self.test_alias_2 = f"APITest_Alias2_{timestamp}"
        self.test_alias_3 = f"APITest_Alias3_{timestamp}"

        # Create test customer in database
        self._create_test_customer()

    def tearDown(self):
        """Clean up test data"""
        try:
            self._cleanup_test_data()
        except Exception as e:
            print(f"Warning: Could not clean up test data: {e}")

    def _create_test_customer(self):
        """Create a test customer in the database"""
        connection, cursor = db_conn()
        try:
            cursor.execute(
                """
                INSERT INTO crm_customers (customer, customer_email, primary_contact)
                VALUES (%s, %s, %s)
            """,
                (self.test_customer, "apitest@example.com", "API Test Contact"),
            )
            connection.commit()
            print(f"✓ Created test customer: {self.test_customer}")
        except Exception as e:
            print(f"❌ Could not create test customer: {e}")
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

    def _cleanup_test_data(self):
        """Remove test customer from database"""
        connection, cursor = db_conn()
        try:
            cursor.execute("DELETE FROM crm_customers WHERE customer = %s", (self.test_customer,))
            connection.commit()
            print(f"✓ Cleaned up test customer: {self.test_customer}")
        except Exception as e:
            print(f"❌ Could not clean up test customer: {e}")
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

    def test_api_get_customer_aliases_empty(self):
        """Test GET /api/crm/customers/{customer}/aliases when empty"""
        print("\n🧪 Testing: GET aliases for empty customer")

        response = self.client.get(f"/api/crm/customers/{self.test_customer}/aliases")

        # Check response
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["aliases"], [])
        self.assertEqual(data["data"]["total_count"], 0)

        print(f"✅ API returned empty aliases for customer '{self.test_customer}'")

    def test_api_post_create_alias(self):
        """Test POST /api/crm/customers/{customer}/aliases"""
        print("\n🧪 Testing: POST create alias")

        response = self.client.post(
            f"/api/crm/customers/{self.test_customer}/aliases",
            json={"alias_name": self.test_alias_1},
            content_type="application/json",
        )

        # Check response
        self.assertEqual(response.status_code, 201)  # Created

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["alias"], self.test_alias_1)
        self.assertEqual(data["data"]["total_aliases"], 1)

        print(f"✅ API created alias '{self.test_alias_1}'")

    def test_api_post_create_duplicate_alias(self):
        """Test POST create duplicate alias (should return conflict)"""
        print("\n🧪 Testing: POST create duplicate alias")

        # First create an alias
        self.client.post(
            f"/api/crm/customers/{self.test_customer}/aliases",
            json={"alias_name": self.test_alias_1},
            content_type="application/json",
        )

        # Try to create duplicate
        response = self.client.post(
            f"/api/crm/customers/{self.test_customer}/aliases",
            json={"alias_name": self.test_alias_1},
            content_type="application/json",
        )

        # Should return conflict
        self.assertEqual(response.status_code, 409)

        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("already exists", data["message"])

        print(f"✅ API prevented duplicate alias '{self.test_alias_1}'")

    def test_api_get_customer_aliases_with_data(self):
        """Test GET /api/crm/customers/{customer}/aliases with actual data"""
        print("\n🧪 Testing: GET aliases with data")

        # First create some aliases
        aliases_to_create = [self.test_alias_1, self.test_alias_2]

        for alias in aliases_to_create:
            response = self.client.post(
                f"/api/crm/customers/{self.test_customer}/aliases",
                json={"alias_name": alias},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)

        # Now get the aliases
        response = self.client.get(f"/api/crm/customers/{self.test_customer}/aliases")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["total_count"], len(aliases_to_create))

        # Verify both aliases are in the response
        for alias in aliases_to_create:
            self.assertIn(alias, data["data"]["aliases"])

        print(f"✅ API returned {len(aliases_to_create)} aliases")

    def test_api_get_specific_alias_exists(self):
        """Test GET /api/crm/customers/{customer}/aliases/{alias} when alias exists"""
        print("\n🧪 Testing: GET specific alias exists")

        # First create an alias
        self.client.post(
            f"/api/crm/customers/{self.test_customer}/aliases",
            json={"alias_name": self.test_alias_1},
            content_type="application/json",
        )

        # Check if alias exists
        response = self.client.get(f"/api/crm/customers/{self.test_customer}/aliases/{self.test_alias_1}")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["alias"], self.test_alias_1)
        self.assertTrue(data["data"]["exists"])

        print(f"✅ API confirmed alias '{self.test_alias_1}' exists")

    def test_api_get_specific_alias_not_exists(self):
        """Test GET /api/crm/customers/{customer}/aliases/{alias} when alias doesn't exist"""
        print("\n🧪 Testing: GET specific alias not exists")

        nonexistent_alias = "NonExistentAlias"

        response = self.client.get(f"/api/crm/customers/{self.test_customer}/aliases/{nonexistent_alias}")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["alias"], nonexistent_alias)
        self.assertFalse(data["data"]["exists"])

        print(f"✅ API confirmed alias '{nonexistent_alias}' doesn't exist")

    def test_api_put_update_alias(self):
        """Test PUT /api/crm/customers/{customer}/aliases/{alias}"""
        print("\n🧪 Testing: PUT update alias")

        # First create an alias
        self.client.post(
            f"/api/crm/customers/{self.test_customer}/aliases",
            json={"alias_name": self.test_alias_1},
            content_type="application/json",
        )

        # Update the alias
        response = self.client.put(
            f"/api/crm/customers/{self.test_customer}/aliases/{self.test_alias_1}",
            json={"new_alias_name": self.test_alias_2},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["old_alias"], self.test_alias_1)
        self.assertEqual(data["data"]["new_alias"], self.test_alias_2)

        print(f"✅ API updated alias '{self.test_alias_1}' to '{self.test_alias_2}'")

    def test_api_delete_alias(self):
        """Test DELETE /api/crm/customers/{customer}/aliases/{alias}"""
        print("\n🧪 Testing: DELETE alias")

        # First create multiple aliases
        aliases_to_create = [self.test_alias_1, self.test_alias_2, self.test_alias_3]

        for alias in aliases_to_create:
            self.client.post(
                f"/api/crm/customers/{self.test_customer}/aliases",
                json={"alias_name": alias},
                content_type="application/json",
            )

        # Delete one alias
        response = self.client.delete(f"/api/crm/customers/{self.test_customer}/aliases/{self.test_alias_2}")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["customer"], self.test_customer)
        self.assertEqual(data["data"]["removed_alias"], self.test_alias_2)
        self.assertEqual(data["data"]["total_aliases"], len(aliases_to_create) - 1)

        print(f"✅ API deleted alias '{self.test_alias_2}'")

    def test_api_delete_nonexistent_alias(self):
        """Test DELETE /api/crm/customers/{customer}/aliases/{alias} when alias doesn't exist"""
        print("\n🧪 Testing: DELETE non-existent alias")

        nonexistent_alias = "NonExistentAlias"

        response = self.client.delete(f"/api/crm/customers/{self.test_customer}/aliases/{nonexistent_alias}")

        self.assertEqual(response.status_code, 404)

        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("not found", data["message"])

        print("✅ API returned 404 for non-existent alias")

    def test_api_invalid_customer(self):
        """Test API with non-existent customer"""
        print("\n🧪 Testing: API with invalid customer")

        invalid_customer = "NonExistentCustomer"

        response = self.client.get(f"/api/crm/customers/{invalid_customer}/aliases")

        self.assertEqual(response.status_code, 404)

        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("not found", data["message"])

        print("✅ API returned 404 for invalid customer")

    def test_api_invalid_request_body(self):
        """Test API with invalid request body"""
        print("\n🧪 Testing: API with invalid request body")

        response = self.client.post(
            f"/api/crm/customers/{self.test_customer}/aliases",
            json={"invalid_field": "value"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Missing required fields", data["message"])

        print("✅ API returned 400 for invalid request")

    def test_complete_api_workflow(self):
        """Test complete CRUD workflow using only API endpoints"""
        print("\n🚀 Testing: Complete API workflow")

        customer = self.test_customer

        # Step 1: Get initial aliases (should be empty)
        response = self.client.get(f"/api/crm/customers/{customer}/aliases")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        initial_count = data["data"]["total_count"]
        print(f"📋 Step 1: Customer '{customer}' has {initial_count} aliases")

        # Step 2: Create first alias
        response = self.client.post(
            f"/api/crm/customers/{customer}/aliases",
            json={"alias_name": self.test_alias_1},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        print(f"➕ Step 2: Created alias '{self.test_alias_1}'")

        # Step 3: Create second alias
        response = self.client.post(
            f"/api/crm/customers/{customer}/aliases",
            json={"alias_name": self.test_alias_2},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        print(f"➕ Step 3: Created alias '{self.test_alias_2}'")

        # Step 4: Verify both aliases exist
        response = self.client.get(f"/api/crm/customers/{customer}/aliases")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["data"]["total_count"], 2)
        print(f"✅ Step 4: Customer now has {data['data']['total_count']} aliases")

        # Step 5: Update first alias
        response = self.client.put(
            f"/api/crm/customers/{customer}/aliases/{self.test_alias_1}",
            json={"new_alias_name": self.test_alias_3},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        print(f"🔄 Step 5: Updated '{self.test_alias_1}' to '{self.test_alias_3}'")

        # Step 6: Verify update
        response = self.client.get(f"/api/crm/customers/{customer}/aliases")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertNotIn(self.test_alias_1, data["data"]["aliases"])
        self.assertIn(self.test_alias_3, data["data"]["aliases"])
        self.assertIn(self.test_alias_2, data["data"]["aliases"])
        print("✅ Step 6: Update verified")

        # Step 7: Delete one alias
        response = self.client.delete(f"/api/crm/customers/{customer}/aliases/{self.test_alias_2}")
        self.assertEqual(response.status_code, 200)
        print(f"🗑️ Step 7: Deleted alias '{self.test_alias_2}'")

        # Step 8: Final verification
        response = self.client.get(f"/api/crm/customers/{customer}/aliases")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        final_aliases = data["data"]["aliases"]
        print(f"🏁 Step 8: Final aliases: {final_aliases}")

        self.assertEqual(len(final_aliases), 1)
        self.assertIn(self.test_alias_3, final_aliases)
        print("🎉 Complete API workflow completed successfully!")


class TestAPIResponseFormats(unittest.TestCase):
    """Test API response format consistency"""

    def setUp(self):
        self.app = app
        self.app.testing = True
        self.client = self.app.test_client()
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.test_customer = f"FormatTest_Customer_{self.timestamp}"
        self.test_alias = f"FormatTest_Alias_{self.timestamp}"
        self._create_test_customer()

    def tearDown(self):
        self._cleanup_test_data()

    def _create_test_customer(self):
        connection, cursor = db_conn()
        try:
            cursor.execute(
                """
                INSERT INTO crm_customers (customer, customer_email)
                VALUES (%s, %s)
            """,
                (self.test_customer, "format@test.com"),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _cleanup_test_data(self):
        connection, cursor = db_conn()
        try:
            cursor.execute("DELETE FROM crm_customers WHERE customer = %s", (self.test_customer,))
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def test_api_response_format_success(self):
        """Test success response format"""
        response = self.client.get(f"/api/crm/customers/{self.test_customer}/aliases")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        # Check required fields
        self.assertIn("success", data)
        self.assertIn("message", data)
        self.assertIn("timestamp", data)
        self.assertIn("data", data)

        # Check success response structure
        self.assertTrue(data["success"])
        self.assertIsInstance(data["timestamp"], str)

        # Check data structure
        api_data = data["data"]
        self.assertIn("customer", api_data)
        self.assertIn("aliases", api_data)
        self.assertIn("total_count", api_data)

    def test_api_response_format_error(self):
        """Test error response format"""
        # Test with invalid customer
        response = self.client.get("/api/crm/customers/NonExistentCustomer.../aliases")

        # Should return appropriate status code based on validation
        self.assertIn(response.status_code, [400, 404])

        data = response.get_json()

        # Check required fields in error response
        self.assertIn("success", data)
        self.assertIn("message", data)
        self.assertIn("timestamp", data)

        # Check error response structure
        self.assertFalse(data["success"])
        self.assertIsInstance(data["message"], str)
        self.assertIsInstance(data["timestamp"], str)


def run_api_integration_tests():
    """Run all API integration tests with detailed output"""

    # Create test suite
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTest(unittest.makeSuite(TestAliasAPIRealEndpoints))
    suite.addTest(unittest.makeSuite(TestAPIResponseFormats))

    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print(f"\n{'=' * 80}")
    print("🎯 CRM Alias API - REAL HTTP ENDPOINT Integration Tests")
    print(f"{'=' * 80}")
    print(f"✅ Tests run: {result.testsRun}")
    print(f"❌ Failures: {len(result.failures)}")
    print(f"❌ Errors: {len(result.errors)}")

    if result.failures:
        print("\n🔍 Test Failures:")
        for test, error in result.failures:
            print(f"  - {test}: {error}")

    if result.errors:
        print("\n🔍 Test Errors:")
        for test, error in result.errors:
            print(f"  - {test}: {error}")

    success_rate = (
        ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100)
        if result.testsRun > 0
        else 0
    )
    print(f"\n🏆 Success Rate: {success_rate:.1f}%")

    if result.wasSuccessful():
        print("🎉 All API endpoint tests passed!")
        print("🔥 Your alias API endpoints work perfectly with HTTP requests!")
    else:
        print("⚠️  Some API endpoint tests failed")

    print(f"{'=' * 80}")
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_api_integration_tests()
    exit(0 if success else 1)
