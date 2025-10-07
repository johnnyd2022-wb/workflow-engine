#!/bin/bash

# Git-based workflow for WhistleBird environments
# This replaces the bashrc functions with a cleaner Git-based approach

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if we're in the right directory
check_directory() {
    if [ ! -f "app.py" ] || [ ! -d "config" ]; then
        print_error "Please run this script from the wb_local directory"
        exit 1
    fi
}

# Function to validate environment
validate_environment() {
    local env=$1
    if [ ! -f "config/${env}.ini" ]; then
        print_error "Configuration file config/${env}.ini not found"
        exit 1
    fi
}

# Function to run local environment
run_local() {
    print_status "Starting LOCAL environment..."
    check_directory
    validate_environment "local"
    
    # Make sure we're on the main branch
    git checkout main
    
    # Run the local environment
    chmod +x scripts/run_local.sh
    ./scripts/run_local.sh
}

# Function to deploy to test
deploy_test() {
    print_status "Deploying to TEST environment..."
    check_directory
    validate_environment "test"
    
    # Make sure we're on the main branch
    git checkout main
    
    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        print_warning "You have uncommitted changes. Stashing them..."
        git stash push -m "Auto-stash before test deployment"
    fi
    
    # Run comprehensive tests before deployment (Semgrep + API tests)
    print_status "🚨 Running pre-deployment test suite..."
    if ! run_all_tests; then
        exit 1
    fi
    
    # Run the test environment
    chmod +x scripts/run_test.sh
    ./scripts/run_test.sh
    
    # Wait for healthcheck to pass
    if wait_for_healthcheck 5001; then
        print_success "Test environment deployed successfully!"
        print_status "Browse to: https://test-inventory.whistlebird.co.nz"
    else
        print_error "Test deployment failed healthcheck. Check logs with: docker logs wb_inv_test"
        exit 1
    fi
}

# Function to deploy to production
deploy_prod() {
    print_status "Deploying to PRODUCTION environment..."
    check_directory
    validate_environment "prod"
    
    # Make sure we're on the main branch
    git checkout main
    
    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        print_warning "You have uncommitted changes. Stashing them..."
        git stash push -m "Auto-stash before production deployment"
    fi
    
    # Run comprehensive tests before deployment (Semgrep + API tests)
    print_status "🚨 Running pre-deployment test suite..."
    if ! run_all_tests; then
        exit 1
    fi
    
    # Create a production tag
    local tag_name="prod-$(date +%Y%m%d-%H%M%S)"
    git tag -a "$tag_name" -m "Production deployment $(date)"
    
    # Run the production environment
    chmod +x scripts/run_prod.sh
    ./scripts/run_prod.sh
    
    # Wait for healthcheck to pass
    if wait_for_healthcheck 5000; then
        print_success "Production environment deployed successfully!"
        print_status "Browse to: https://inventory.whistlebird.co.nz"
        print_status "Deployment tagged as: $tag_name"
        
        # Push the tag to remote only after successful healthcheck
        print_status "Pushing deployment tag to remote..."
        if git push origin "$tag_name"; then
            print_success "Deployment tag pushed successfully: $tag_name"
        else
            print_warning "Failed to push tag to remote, but deployment is healthy"
        fi
    else
        print_error "Production deployment failed healthcheck. Check logs with: docker logs wb_inv_prod"
        print_warning "Removing local tag since deployment failed"
        git tag -d "$tag_name"
        exit 1
    fi
}

# Function to restore test database
restore_test_db() {
    print_status "Restoring production database to test environment..."
    check_directory

    chmod +x scripts/db_restore.sh
    ./scripts/db_restore.sh

    print_success "Test database restored successfully!"
}

# Function to show status of all environments
status() {
    print_status "Environment Status:"
    echo ""

    # Check local environment
    if pgrep -f "python3 app.py" > /dev/null; then
        print_success "LOCAL: Running"
    else
        print_warning "LOCAL: Not running"
    fi

    # Check test environment
    if docker ps --format "table {{.Names}}" | grep -q "wb_inv_test"; then
        print_success "TEST: Running (Docker)"
    else
        print_warning "TEST: Not running"
    fi

    # Check production environment
    if docker ps --format "table {{.Names}}" | grep -q "wb_inv_prod"; then
        print_success "PRODUCTION: Running (Docker)"
    else
        print_warning "PRODUCTION: Not running"
    fi
    
    echo ""
    print_status "Git Status:"
    git status --short
}

# Function to run Semgrep compliance tests
run_semgrep_tests() {
    print_status "Running Semgrep alias compliance tests..."
    
    # Check if Semgrep is installed
    if ! command -v semgrep &> /dev/null; then
        print_error "Semgrep not found. Please install semgrep first:"
        print_error "  pip install semgrep"
        print_error "  or: pip3 install semgrep"
        return 1
    fi
    
    # Check if our Semgrep config exists
    if [ ! -f "features/crm/tests/semgrep_alias_rules.yml" ]; then
        print_error "Semgrep configuration not found: features/crm/tests/semgrep_alias_rules.yml"
        return 1
    fi
    
    print_status "🔍 Running alias compliance scan on features directory..."
    
    # Run Semgrep and capture output
    local semgrep_output
    local semgrep_exit_code
    
    semgrep_output=$(semgrep --config features/crm/tests/semgrep_alias_rules.yml features/ --verbose 2>&1)
    semgrep_exit_code=$?
    
    # Display the Semgrep output
    echo "$semgrep_output"
    
    if [ $semgrep_exit_code -eq 0 ]; then
        # Check if any findings were reported in the output
        if echo "$semgrep_output" | grep -q "Findings:"; then
            local findings_count=$(echo "$semgrep_output" | grep "Findings:" | grep -o '[0-9]\+' | head -1)
            
            if [ "$findings_count" -gt 0 ]; then
                print_error "❌ SEMGREP COMPLIANCE VIOLATIONS DETECTED!"
                print_error "🔒 Found $findings_count alias compliance violations"
                print_error "💰 Fix these violations before deploying to production"
                print_error "📋 Use proper alias API endpoints instead of legacy routes"
                return 1
            else
                print_success "✅ SEMGREP COMPLIANCE TESTS PASSED!"
                print_success "🎯 No alias compliance violations detected"
                return 0
            fi
        else
            print_success "✅ SEMGREP COMPLIANCE TESTS PASSED!"
            print_success "🎯 No alias compliance violations detected"
            return 0
        fi
    else
        print_error "❌ Semgrep scan failed!"
        print_error "🔧 Check Semgrep configuration and installation"
        print_error "💡 Verify: pip install semgrep"
        return 1
    fi
}

# Function to run API integration tests
run_api_tests() {
    print_status "Running comprehensive API test suite..."
    
    # Check if our centralized test runner exists
    if [ ! -f "scripts/run_all_api_tests.py" ]; then
        print_error "Centralized test runner not found: scripts/run_all_api_tests.py"
        print_error "Please create scripts/run_all_api_tests.py for dynamic test discovery"
        exit 1
    fi
    
    # Make sure we're in the correct directory for imports
    export PYTHONPATH="$(pwd):$PYTHONPATH"
    
    print_status "🚨 Executing comprehensive API test suite..."
    
    # Run the centralized test runner
    # It will return 0 if all tests pass, 1 if any fail
    if wsl python3 scripts/run_all_api_tests.py; then
        # Test runner passed - all tests successful
        print_success "✅ ALL API TESTS PASSED!"
        print_success "🚀 Deployment approved - all tests green!"
        return 0
    else
        # Test runner failed - tests failed or errors occurred
        print_error "❌ API tests failed!"
        print_error "🔒 Deployment BLOCKED - all tests must pass"
        print_error "💡 See test output above for specific failures"
        print_error "🔧 Fix failing tests before deploying to production"
        return 1
    fi
}

# Function to run all pre-deployment tests
run_all_tests() {
    print_status "🚨 Running comprehensive pre-deployment test suite..."
    
    # Run Semgrep compliance tests first
    print_status "Step 1/2: Running Semgrep compliance tests..."
    if ! run_semgrep_tests; then
        print_error "🔒 Deployment BLOCKED - Semgrep compliance violations detected"
        return 1
    fi
    
    # Run API integration tests
    print_status "Step 2/2: Running API integration tests..."
    if ! run_api_tests; then
        print_error "🔒 Deployment BLOCKED - API tests failed"
        return 1
    fi
    
    # All tests passed
    print_success "🎉 ALL PRE-DEPLOYMENT TESTS PASSED!"
    print_success "🚀 Deployment approved - compliance checks and API tests green!"
    return 0
}

# Function to wait for healthcheck
wait_for_healthcheck() {
    local port=$1
    local max_attempts=30
    local attempt=1

    print_status "Waiting for healthcheck to pass on port $port..."

    while [ $attempt -le $max_attempts ]; do
        if curl -f -k -s "https://localhost:$port/healthcheck" > /dev/null 2>&1; then
            print_success "Healthcheck passed! Application is healthy."
            return 0
        fi

        print_status "Attempt $attempt/$max_attempts: Healthcheck not ready yet, waiting 10 seconds..."
        sleep 10
        attempt=$((attempt + 1))
    done

    print_error "Healthcheck failed after $max_attempts attempts. Application may not be healthy."
    return 1
}

# Function to show help
show_help() {
    echo "WhistleBird Git Workflow"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  local       Run local environment (python3 app.py)"
    echo "  test        Deploy to test environment (Docker) - includes Semgrep + API tests"
    echo "  prod        Deploy to production environment (Docker) - includes Semgrep + API tests"
    echo "  restore-db  Restore production DB to test environment"
    echo "  status      Show status of all environments"
    echo "  tests       Run API integration tests only"
    echo "  compliance  Run Semgrep alias compliance tests only"
    echo "  all-tests   Run comprehensive test suite (Semgrep + API tests)"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 local      # Start local development"
    echo "  $0 tests      # Run API tests only"
    echo "  $0 compliance # Run Semgrep compliance tests only"
    echo "  $0 all-tests  # Run comprehensive test suite"
    echo "  $0 test       # Deploy to test (with comprehensive tests)"
    echo "  $0 prod       # Deploy to production (with comprehensive tests)"
    echo "  $0 status     # Check all environments"
    echo ""
    echo "🚨 Note: Test and production deployments will run comprehensive tests (Semgrep + API) before deploying."
    echo "    If tests fail, deployment will be blocked to prevent errors in production."
}

# Main script logic
case "${1:-help}" in
    "local")
        run_local
        ;;
    "test")
        deploy_test
        ;;
    "prod")
        deploy_prod
        ;;
    "tests")
        run_api_tests
        ;;
    "compliance")
        run_semgrep_tests
        ;;
    "all-tests")
        run_all_tests
        ;;
    "restore-db")
        restore_test_db
        ;;
    "status")
        status
        ;;
    "help"|"--help"|"-h")
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac