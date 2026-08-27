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

    // RDS PostgreSQL 15, db.t4g.small, final snapshot retained on removal
    template.resourceCountIs('AWS::RDS::DBInstance', 1);
    template.hasResourceProperties('AWS::RDS::DBInstance', {
      Engine: 'postgres',
      DBInstanceClass: 'db.t4g.small',
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

  test('wires the three app secrets and composed DATABASE_URL (AWS-4)', () => {
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

    // Container definition wires all three as task-definition secrets
    // plus DATABASE_URL in the environment. NOTE: Match.arrayWith patterns
    // must be listed in array order (DATABASE_URL is the last env entry).
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Name: 'App',
          Secrets: Match.arrayWith([
            Match.objectLike({ Name: 'TELEGRAM_BOT_TOKEN' }),
            Match.objectLike({ Name: 'TELEGRAM_WEBHOOK_SECRET' }),
            Match.objectLike({ Name: 'GEMINI_API_KEY' }),
          ]),
          Environment: Match.arrayWith([
            Match.objectLike({ Name: 'TELEGRAM_WEBHOOK_URL' }),
            Match.objectLike({ Name: 'STORE_PROVIDER', Value: 'pgvector' }),
            Match.objectLike({ Name: 'DATABASE_URL' }),
          ]),
        }),
      ]),
    });

    // Execution role can resolve the RDS secret used by DATABASE_URL
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

    // Recent aws-cdk-lib versions back the OIDC provider with a custom
    // resource (thumbprint auto-management); the deployed provider carries
    // the documented URL, client id and GitHub thumbprint.
    template.resourceCountIs('Custom::AWSCDKOpenIdConnectProvider', 1);
    template.hasResourceProperties('Custom::AWSCDKOpenIdConnectProvider', {
      Url: 'https://token.actions.githubusercontent.com',
      ClientIDList: ['sts.amazonaws.com'],
      ThumbprintList: ['6938fd4d98bab03faadb97b34396831e3780aea1'],
    });

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