#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}👤 Cognito User Creation${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

# Get User Pool ID from CloudFormation outputs
REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name FashionAuthStack --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --region "$REGION" 2>/dev/null)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name FashionAuthStack --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --region "$REGION" 2>/dev/null)

if [ -z "$USER_POOL_ID" ] || [ "$USER_POOL_ID" = "None" ]; then
    echo -e "${RED}❌ FashionAuthStack not deployed. Run ./deploy.sh first.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ User Pool: ${USER_POOL_ID}${NC}"
echo -e "${GREEN}✅ Client ID: ${CLIENT_ID}${NC}\n"

# Collect input
read -rp "$(echo -e "${BLUE}📧 Email: ${NC}")" EMAIL
read -rp "$(echo -e "${BLUE}👤 Full Name: ${NC}")" FULLNAME
read -srp "$(echo -e "${BLUE}🔑 Password (min 8, upper+lower+digit+symbol): ${NC}")" PASSWORD
echo ""

if [ -z "$EMAIL" ] || [ -z "$FULLNAME" ] || [ -z "$PASSWORD" ]; then
    echo -e "${RED}❌ All fields are required${NC}"
    exit 1
fi

# Create user
echo -e "\n${YELLOW}⏳ Creating user...${NC}"
aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true Name=name,Value="$FULLNAME" \
    --message-action SUPPRESS \
    --region "$REGION" > /dev/null

# Set permanent password
aws cognito-idp admin-set-user-password \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --password "$PASSWORD" \
    --permanent \
    --region "$REGION"

echo -e "${GREEN}✅ User created and confirmed!${NC}\n"

# Test auth and get token
echo -e "${YELLOW}⏳ Testing authentication...${NC}"
AUTH_RESULT=$(aws cognito-idp initiate-auth \
    --auth-flow USER_PASSWORD_AUTH \
    --client-id "$CLIENT_ID" \
    --auth-parameters USERNAME="$EMAIL",PASSWORD="$PASSWORD" \
    --region "$REGION" 2>&1)

if echo "$AUTH_RESULT" | grep -q "IdToken"; then
    ID_TOKEN=$(echo "$AUTH_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['AuthenticationResult']['IdToken'])")
    echo -e "${GREEN}✅ Authentication successful!${NC}\n"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}📋 Summary${NC}"
    echo -e "  ${GREEN}Email${NC}:     $EMAIL"
    echo -e "  ${GREEN}Name${NC}:      $FULLNAME"
    echo -e "  ${GREEN}Pool ID${NC}:   $USER_POOL_ID"
    echo -e "  ${GREEN}Client ID${NC}: $CLIENT_ID"
    echo -e "\n${BLUE}🔑 ID Token (use as Authorization header):${NC}"
    echo -e "${YELLOW}${ID_TOKEN:0:80}...${NC}"
    echo -e "\n${BLUE}💡 Usage:${NC}"
    echo -e "  curl -H \"Authorization: \$TOKEN\" <api-url>/v1/profile"
else
    echo -e "${RED}❌ Auth failed: ${AUTH_RESULT}${NC}"
    exit 1
fi
