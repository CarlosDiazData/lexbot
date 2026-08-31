import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { LexBotStack } from '../lib/lexbot-stack';

/**
 * Shared fixture: a LexBotStack with fixed env + the context values the
 * deploy uses (imageTag is required and provided here as "test").
 */
function makeStack(extraContext: Record<string, unknown> = {}): LexBotStack {
  const app = new cdk.App({
    context: {
      region: 'us-east-1',
      envName: 'prod',
      imageTag: 'test',
      ...extraContext,
    },
  });
  return new LexBotStack(app, 'LexBotStack', {
    env: { account: '111122223333', region: 'us-east-1' },
  });
}

describe('LexBotStack', () => {
  test('throws when imageTag context is missing', () => {
    const app = new cdk.App({ context: {} });
    expect(() => new LexBotStack(app, 'LexBotStack')).toThrow(/imageTag/);
  });

  test('provisions the core compute resources (AWS-2)', () => {
    const template = Template.fromStack(makeStack());

    // ECS Fargate service: 1 task, 300s health-check grace period
    template.resourceCountIs('AWS::ECS::Service', 1);
    template.hasResourceProperties('AWS::ECS::Service', {
      DesiredCount: 1,
      HealthCheckGracePeriodSeconds: 300,
      LaunchType: 'FARGATE',
    });

    // RDS PostgreSQL 15, db.t4g.micro (Free Tier compatible), final snapshot retained on removal
    template.resourceCountIs('AWS::RDS::DBInstance', 1);
    template.hasResourceProperties('AWS::RDS::DBInstance', {
      Engine: 'postgres',
      DBInstanceClass: 'db.t4g.micro',
      EngineVersion: Match.stringLikeRegexp('15.*'),
      MultiAZ: false,
      DBName: 'lexbot',
    });
    template.hasResource('AWS::RDS::DBInstance', {
      DeletionPolicy: 'Snapshot',
      UpdateReplacePolicy: 'Snapshot',
    });

    // ECR repository + log group
    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'lexbot',
      ImageScanningConfiguration: { ScanOnPush: true },
    });
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/ecs/lexbot',
      RetentionInDays: 30,
    });
  });

  test('ALB keeps an HTTP-only listener; CloudFront is the HTTPS edge (AWS-3)', () => {
    const template = Template.fromStack(makeStack());

    template.resourceCountIs('AWS::ElasticLoadBalancingV2::LoadBalancer', 1);
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::Listener', {
      Port: 80,
      Protocol: 'HTTP',
    });

    // No HTTPS listener on the ALB (approved deviation)
    const listeners = template.findResources('AWS::ElasticLoadBalancingV2::Listener');
    for (const listener of Object.values(listeners)) {
      expect(listener.Properties.Protocol).toBe('HTTP');
    }

    // CloudFront: CachingDisabled policy, ALL_VIEWER request policy
    // (forwards all headers incl. X-Telegram-Bot-Api-Secret-Token), POST allowed
    template.resourceCountIs('AWS::CloudFront::Distribution', 1);
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: {
        DefaultCacheBehavior: {
          // Managed policy IDs: CachingDisabled / ALL_VIEWER
          CachePolicyId: '4135ea2d-6df8-44a3-9df3-4b5a84be39ad',
          OriginRequestPolicyId: '216adef6-5c7f-47e4-b989-5492eafa07d3',
          // ALLOW_ALL renders in this order (arrayWith is order-sensitive)
          AllowedMethods: Match.arrayWith(['GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'POST', 'DELETE']),
          ViewerProtocolPolicy: 'redirect-to-https',
        },
      },
    });
  });

  test('wires the app secrets, database connection, and security groups (AWS-4)', () => {
    const template = Template.fromStack(makeStack());

    // Placeholder secrets exist under the documented names
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'lexbot/telegram/bot-token',
    });
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'lexbot/telegram/webhook-secret',
    });
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'lexbot/gemini/api-key',
    });

    // Container definition wires secrets + PG* environment variables
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Name: 'App',
          Secrets: Match.arrayWith([
            Match.objectLike({ Name: 'TELEGRAM_BOT_TOKEN' }),
            Match.objectLike({ Name: 'TELEGRAM_WEBHOOK_SECRET' }),
            Match.objectLike({ Name: 'GEMINI_API_KEY' }),
            Match.objectLike({ Name: 'PGUSER' }),
            Match.objectLike({ Name: 'PGPASSWORD' }),
          ]),
          Environment: Match.arrayWith([
            Match.objectLike({ Name: 'TELEGRAM_WEBHOOK_URL' }),
            Match.objectLike({ Name: 'STORE_PROVIDER', Value: 'pgvector' }),
            Match.objectLike({ Name: 'PGHOST' }),
            Match.objectLike({ Name: 'PGPORT' }),
            Match.objectLike({ Name: 'PGDATABASE', Value: 'lexbot' }),
          ]),
        }),
      ]),
    });

    // RDS Security Group allows ingress from ECS Service
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      IpProtocol: 'tcp',
      Description: Match.stringLikeRegexp('.*ServiceSecurityGroup.*'),
    });

    // Execution role can resolve secrets
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: 'secretsmanager:GetSecretValue',
          }),
        ]),
      },
    });
  });

  test('creates the $45 budget alarm and the memory alarm (AWS-5)', () => {
    const template = Template.fromStack(makeStack());

    template.hasResourceProperties('AWS::Budgets::Budget', {
      Budget: {
        BudgetType: 'COST',
        TimeUnit: 'MONTHLY',
        BudgetLimit: { Amount: 45, Unit: 'USD' },
      },
    });
    template.resourceCountIs('AWS::SNS::Topic', 1);

    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      Namespace: 'ECS/ContainerInsights',
      MetricName: 'MemoryUtilized',
      ComparisonOperator: 'GreaterThanOrEqualToThreshold',
      Threshold: 870,
      EvaluationPeriods: 1,
    });
  });

  test('includes the OIDC deploy role scoped to the app stack (AWS-6)', () => {
    const template = Template.fromStack(makeStack());

    // GitHub's OIDC provider is imported from the account ARN
    template.resourceCountIs('Custom::AWSCDKOpenIdConnectProvider', 0);

    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'sts:AssumeRoleWithWebIdentity',
            Condition: {
              StringEquals: { 'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com' },
              StringLike: {
                'token.actions.githubusercontent.com:sub': 'repo:CarlosDiazData/lexbot:*',
              },
            },
          }),
        ]),
      },
    });

    // No static credentials anywhere
    template.resourceCountIs('AWS::IAM::AccessKey', 0);
  });
});