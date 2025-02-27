import pytest

from localstack.testing.pytest.fixtures import _client
from localstack.utils.strings import short_uid


@pytest.fixture
def client_factory():
    def _client_factory(service: str, aws_access_key_id: str, region_name: str = "eu-central-1"):
        return _client(service, region_name=region_name, aws_access_key_id=aws_access_key_id)

    yield _client_factory


class TestMultiAccounts:
    def test_account_id_namespacing_for_moto_backends(self, client_factory):
        #
        # ACM
        #

        account_id1 = "420420420420"
        account_id2 = "133713371337"

        # Ensure resources are isolated by account ID namespaces
        acm_client1 = client_factory("acm", account_id1)
        acm_client2 = client_factory("acm", account_id2)

        acm_client1.request_certificate(DomainName="example.com")

        certs = acm_client1.list_certificates()
        assert len(certs["CertificateSummaryList"]) == 1

        certs = acm_client2.list_certificates()
        assert len(certs["CertificateSummaryList"]) == 0

        #
        # EC2
        #

        ec2_client1 = client_factory("ec2", account_id1)
        ec2_client2 = client_factory("ec2", account_id2)

        # Ensure resources are namespaced by account ID
        ec2_client1.create_key_pair(KeyName="lorem")
        pairs = ec2_client1.describe_key_pairs()
        assert len(pairs["KeyPairs"]) == 1

        pairs = ec2_client2.describe_key_pairs()
        assert len(pairs["KeyPairs"]) == 0

        # Ensure name conflicts don't happen across namespaces
        ec2_client2.create_key_pair(KeyName="lorem")
        ec2_client2.create_key_pair(KeyName="ipsum")

        pairs = ec2_client2.describe_key_pairs()
        assert len(pairs["KeyPairs"]) == 2

        pairs = ec2_client1.describe_key_pairs()
        assert len(pairs["KeyPairs"]) == 1

        # Ensure account ID resolver is correctly patched in Moto
        # Calls originating in Moto must make use of client provided account ID
        ec2_client1.create_vpc(CidrBlock="10.1.0.0/16")
        vpcs = ec2_client1.describe_vpcs()["Vpcs"]
        assert all([vpc["OwnerId"] == account_id1 for vpc in vpcs])

    def test_account_id_namespacing_for_localstack_backends(self, client_factory):
        # Ensure resources are isolated by account ID namespaces
        account_id1 = "420420420420"
        account_id2 = "133713371337"

        sns_client1 = client_factory("sns", account_id1)
        sns_client2 = client_factory("sns", account_id2)

        arn1 = sns_client1.create_topic(Name="foo")["TopicArn"]

        assert len(sns_client1.list_topics()["Topics"]) == 1
        assert len(sns_client2.list_topics()["Topics"]) == 0

        arn2 = sns_client2.create_topic(Name="foo")["TopicArn"]
        arn3 = sns_client2.create_topic(Name="bar")["TopicArn"]

        assert len(sns_client1.list_topics()["Topics"]) == 1
        assert len(sns_client2.list_topics()["Topics"]) == 2

        sns_client1.tag_resource(ResourceArn=arn1, Tags=[{"Key": "foo", "Value": "1"}])

        assert len(sns_client1.list_tags_for_resource(ResourceArn=arn1)["Tags"]) == 1
        assert len(sns_client2.list_tags_for_resource(ResourceArn=arn2)["Tags"]) == 0
        assert len(sns_client2.list_tags_for_resource(ResourceArn=arn3)["Tags"]) == 0

        sns_client2.tag_resource(ResourceArn=arn2, Tags=[{"Key": "foo", "Value": "1"}])
        sns_client2.tag_resource(ResourceArn=arn2, Tags=[{"Key": "bar", "Value": "1"}])
        sns_client2.tag_resource(ResourceArn=arn3, Tags=[{"Key": "foo", "Value": "1"}])

        assert len(sns_client1.list_tags_for_resource(ResourceArn=arn1)["Tags"]) == 1
        assert len(sns_client2.list_tags_for_resource(ResourceArn=arn2)["Tags"]) == 2
        assert len(sns_client2.list_tags_for_resource(ResourceArn=arn3)["Tags"]) == 1

    def test_multi_accounts_dynamodb(self, client_factory, cleanups):
        """DynamoDB depends on an external service - DynamoDB Local"""
        account_id1 = "420420420420"
        account_id2 = "133713371337"

        ddb_client1 = client_factory("dynamodb", account_id1, region_name="ap-south-1")
        ddb_client2 = client_factory("dynamodb", account_id1)
        ddb_client3 = client_factory("dynamodb", account_id2)

        tab1 = f"table-{short_uid()}"

        # The CreateTable call gets forwarded to DDBLocal.
        # The assertions below test whether DDBLocal correctly namespaces the tables.

        response1 = ddb_client1.create_table(
            TableName=tab1,
            KeySchema=[{"AttributeName": "Username", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "Username", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        cleanups.append(lambda: ddb_client1.delete_table(TableName=tab1))
        assert (
            response1["TableDescription"]["TableArn"]
            == f"arn:aws:dynamodb:ap-south-1:{account_id1}:table/{tab1}"
        )

        # Create table with the same name in a different region
        response2 = ddb_client2.create_table(
            TableName=tab1,
            KeySchema=[{"AttributeName": "Username", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "Username", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        cleanups.append(lambda: ddb_client2.delete_table(TableName=tab1))
        assert (
            response2["TableDescription"]["TableArn"]
            == f"arn:aws:dynamodb:eu-central-1:{account_id1}:table/{tab1}"
        )

        # Create table with the same name in a different account
        response3 = ddb_client3.create_table(
            TableName=tab1,
            KeySchema=[{"AttributeName": "Username", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "Username", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        cleanups.append(lambda: ddb_client3.delete_table(TableName=tab1))
        assert (
            response3["TableDescription"]["TableArn"]
            == f"arn:aws:dynamodb:eu-central-1:{account_id2}:table/{tab1}"
        )
