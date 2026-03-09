#!/bin/bash
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

BACKEND_STACKS=("FashionDbStack" "FashionAuthStack" "FashionStorageStack" "FashionApiStack")
FRONTEND_STACKS=("FashionFrontendStack")

usage() {
  echo -e "${CYAN}Usage:${NC} ./deploy.sh [all|backend|frontend]"
  echo -e "  ${GREEN}all${NC}       Deploy backend then frontend (default)"
  echo -e "  ${GREEN}backend${NC}   Deploy backend stacks only"
  echo -e "  ${GREEN}frontend${NC}  Redeploy frontend (picks up API URL from deployed backend)"
  exit 0
}

case "${1:-all}" in
  backend)  STACKS=("${BACKEND_STACKS[@]}"); LABEL="Backend" ;;
  frontend) STACKS=("${FRONTEND_STACKS[@]}"); LABEL="Frontend" ;;
  all)      STACKS=("${BACKEND_STACKS[@]}" "${FRONTEND_STACKS[@]}"); LABEL="Full" ;;
  -h|--help|help) usage ;;
  *) echo -e "${RED}❌ Unknown target: $1${NC}"; usage ;;
esac

echo -e "${CYAN}🚀 Atelier Fashion — ${LABEL} Deployment${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

# Prerequisites
echo -e "${BLUE}🔍 Checking prerequisites...${NC}"
command -v cdk >/dev/null 2>&1 || { echo -e "${RED}❌ CDK CLI not found${NC}"; exit 1; }
aws sts get-caller-identity >/dev/null 2>&1 || { echo -e "${RED}❌ AWS credentials not configured${NC}"; exit 1; }
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
echo -e "${GREEN}✅ Account: ${ACCOUNT} | Region: ${REGION}${NC}\n"

# Venv
if [ -d ".venv" ]; then
  source .venv/bin/activate
else
  echo -e "${YELLOW}⚠️  Creating virtualenv...${NC}"
  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -q
fi

# Synth
echo -e "${BLUE}🔨 Synthesizing...${NC}"
if cdk synth --quiet 2>&1 | grep -q "Found errors"; then
  echo -e "${RED}❌ CDK Nag errors. Run 'cdk synth' for details.${NC}"; exit 1
fi
echo -e "${GREEN}✅ Synth passed${NC}\n"

# Bootstrap
if ! aws cloudformation describe-stacks --stack-name CDKToolkit --region "$REGION" >/dev/null 2>&1; then
  echo -e "${YELLOW}🏗️  Bootstrapping...${NC}"
  cdk bootstrap "aws://${ACCOUNT}/${REGION}"
fi

# Deploy
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}📦 Deploying ${#STACKS[@]} stack(s)...${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

FAILED=0
for STACK in "${STACKS[@]}"; do
  echo -e "${YELLOW}⏳ ${STACK}${NC}"
  if cdk deploy "$STACK" --require-approval never 2>&1 | tee /tmp/cdk_deploy_${STACK}.log | grep -E "✅|❌|Outputs|Error"; then
    echo -e "${GREEN}✅ ${STACK}${NC}\n"
  else
    echo -e "${RED}❌ ${STACK} — see /tmp/cdk_deploy_${STACK}.log${NC}\n"
    FAILED=1
  fi
done

# CloudFront cache invalidation (frontend deploys)
if [[ " ${STACKS[*]} " =~ "FashionFrontendStack" ]] && [ $FAILED -eq 0 ]; then
  DIST_ID=$(aws cloudformation list-stack-resources --stack-name FashionFrontendStack \
    --query "StackResourceSummaries[?ResourceType=='AWS::CloudFront::Distribution'].PhysicalResourceId" \
    --output text 2>/dev/null)
  if [ -n "$DIST_ID" ]; then
    echo -e "${YELLOW}🔄 Invalidating CloudFront cache (${DIST_ID})...${NC}"
    aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" --output text >/dev/null 2>&1
    echo -e "${GREEN}✅ Cache invalidation submitted${NC}\n"
  fi
fi

# Summary
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}🎉 ${LABEL} deployment complete!${NC}\n"

  # Show key outputs
  API_URL=$(aws cloudformation describe-stacks --stack-name FashionApiStack --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text 2>/dev/null || echo "")
  FRONTEND_URL=$(aws cloudformation describe-stacks --stack-name FashionFrontendStack --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" --output text 2>/dev/null || echo "")
  POOL_ID=$(aws cloudformation describe-stacks --stack-name FashionAuthStack --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text 2>/dev/null || echo "")
  CLIENT_ID=$(aws cloudformation describe-stacks --stack-name FashionAuthStack --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text 2>/dev/null || echo "")

  echo -e "${BLUE}📋 Endpoints:${NC}"
  [ -n "$FRONTEND_URL" ] && echo -e "  ${GREEN}🌐 Frontend${NC}:  ${FRONTEND_URL}"
  [ -n "$API_URL" ]      && echo -e "  ${GREEN}⚡ API${NC}:       ${API_URL}"
  [ -n "$POOL_ID" ]      && echo -e "  ${GREEN}🔐 Pool ID${NC}:   ${POOL_ID}"
  [ -n "$CLIENT_ID" ]    && echo -e "  ${GREEN}🔑 Client ID${NC}: ${CLIENT_ID}"

  if [ -n "$API_URL" ] && [ -n "$FRONTEND_URL" ]; then
    echo -e "\n  ${CYAN}✨ API URL is baked into frontend config.js at deploy time${NC}"
  fi
else
  echo -e "${RED}💥 Deployment had errors. Check logs above.${NC}"; exit 1
fi
