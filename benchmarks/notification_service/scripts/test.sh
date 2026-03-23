#!/bin/bash
set -e

echo "=== Notification Service Test Runner ==="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  unit        Run unit tests only (no Redis required)"
    echo "  integration Run integration tests (requires Redis)"
    echo "  all         Run all tests (requires Redis)"
    echo "  docker      Run all tests in Docker containers"
    echo "  coverage    Run tests with coverage report"
    echo ""
    exit 1
}

run_unit_tests() {
    echo -e "${YELLOW}Running unit tests...${NC}"
    python -m pytest test_service.py -v --tb=short
}

run_integration_tests() {
    echo -e "${YELLOW}Running integration tests...${NC}"
    python -m pytest test_integration.py -v --tb=short
}

run_all_tests() {
    echo -e "${YELLOW}Running all tests...${NC}"
    python -m pytest . -v --tb=short
}

run_docker_tests() {
    echo -e "${YELLOW}Running tests in Docker...${NC}"
    docker-compose -f docker-compose.test.yml build
    docker-compose -f docker-compose.test.yml run --rm test-runner
    docker-compose -f docker-compose.test.yml down
}

run_coverage() {
    echo -e "${YELLOW}Running tests with coverage...${NC}"
    python -m pytest . -v --cov=. --cov-report=term-missing --cov-report=html
    echo -e "${GREEN}Coverage report generated in htmlcov/${NC}"
}

cd "$(dirname "$0")/.."

case "${1:-all}" in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
        ;;
    all)
        run_all_tests
        ;;
    docker)
        run_docker_tests
        ;;
    coverage)
        run_coverage
        ;;
    *)
        usage
        ;;
esac

echo -e "${GREEN}Tests completed!${NC}"
