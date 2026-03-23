#!/bin/bash
set -e

echo "=== Notification Service Deployment ==="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Usage: $0 [environment] [options]"
    echo ""
    echo "Environments:"
    echo "  local       Deploy to local Docker Compose"
    echo "  k8s         Deploy to Kubernetes cluster"
    echo ""
    echo "Options:"
    echo "  --build     Build images before deploying"
    echo "  --dry-run   Show what would be deployed (k8s only)"
    echo ""
    exit 1
}

ENVIRONMENT="${1:-local}"
BUILD=false
DRY_RUN=false

shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            usage
            ;;
    esac
done

cd "$(dirname "$0")/.."

deploy_local() {
    echo -e "${YELLOW}Deploying to local Docker Compose...${NC}"

    if [ "$BUILD" = true ]; then
        echo "Building images..."
        docker-compose build
    fi

    docker-compose up -d

    echo -e "${GREEN}Service deployed!${NC}"
    echo ""
    echo "Endpoints:"
    echo "  - API: http://localhost:8000"
    echo "  - Health: http://localhost:8000/health"
    echo "  - Stats: http://localhost:8000/stats"
    echo ""
    echo "Commands:"
    echo "  - Logs: docker-compose logs -f notification-service"
    echo "  - Stop: docker-compose down"
}

deploy_k8s() {
    echo -e "${YELLOW}Deploying to Kubernetes...${NC}"

    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}kubectl not found. Please install kubectl first.${NC}"
        exit 1
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "Dry run - showing manifests:"
        kubectl kustomize k8s/
        echo ""
        echo "To apply: kubectl apply -k k8s/"
        return
    fi

    if [ "$BUILD" = true ]; then
        echo "Building and pushing image..."
        REGISTRY="${REGISTRY:-localhost:5000}"
        TAG="${TAG:-latest}"
        docker build -t "$REGISTRY/notification-service:$TAG" .
        docker push "$REGISTRY/notification-service:$TAG"

        # Update image in deployment
        kubectl -n notification-service set image deployment/notification-service \
            notification-service="$REGISTRY/notification-service:$TAG"
    fi

    echo "Applying Kubernetes manifests..."
    kubectl apply -k k8s/

    echo "Waiting for deployment..."
    kubectl -n notification-service rollout status deployment/notification-service --timeout=120s

    echo -e "${GREEN}Deployment complete!${NC}"
    echo ""
    echo "Commands:"
    echo "  - Logs: kubectl -n notification-service logs -f deployment/notification-service"
    echo "  - Port-forward: kubectl -n notification-service port-forward svc/notification-service 8000:80"
    echo "  - Status: kubectl -n notification-service get pods"
}

case "$ENVIRONMENT" in
    local)
        deploy_local
        ;;
    k8s)
        deploy_k8s
        ;;
    *)
        usage
        ;;
esac
