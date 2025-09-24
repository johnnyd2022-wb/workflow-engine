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
    
    # Run the test environment
    chmod +x scripts/run_test.sh
    ./scripts/run_test.sh
    
    print_success "Test environment deployed successfully!"
    print_status "Browse to: https://test-inventory.whistlebird.co.nz"
}

# Function to deploy to production
deploy_prod() {
    print_status "Deploying to PRODUCTION environment..."
    check_directory
    validate_environment "production"
    
    # Make sure we're on the main branch
    git checkout main
    
    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        print_warning "You have uncommitted changes. Stashing them..."
        git stash push -m "Auto-stash before production deployment"
    fi
    
    # Create a production tag
    local tag_name="prod-$(date +%Y%m%d-%H%M%S)"
    git tag -a "$tag_name" -m "Production deployment $(date)"
    
    # Run the production environment
    chmod +x scripts/run_prod.sh
    ./scripts/run_prod.sh
    
    print_success "Production environment deployed successfully!"
    print_status "Browse to: https://inventory.whistlebird.co.nz"
    print_status "Deployment tagged as: $tag_name"
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

# Function to show help
show_help() {
    echo "WhistleBird Git Workflow"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  local       Run local environment (python3 app.py)"
    echo "  test        Deploy to test environment (Docker)"
    echo "  prod        Deploy to production environment (Docker)"
    echo "  restore-db  Restore production DB to test environment"
    echo "  status      Show status of all environments"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 local      # Start local development"
    echo "  $0 test       # Deploy to test"
    echo "  $0 prod       # Deploy to production"
    echo "  $0 status     # Check all environments"
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