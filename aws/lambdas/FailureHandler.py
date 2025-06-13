import json
import boto3
import os

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
SINGLE_FILE_PACKAGER_NAME = os.environ['SINGLE_FILE_PACKAGER_NAME']
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

def lambda_handler(event, context):
    print(f"FailureHandler received {len(event.get('Records', []))} records from DLQ.")
    
    for record in event['Records']:
        try:
            original_message = json.loads(record['body'])
            task_id = original_message.get('taskId')

            if not task_id:
                print(f"Could not find taskId in DLQ message body: {record['body']}")
                continue
            
            print(f"Processing failed task {task_id} from DLQ.")

            table.update_item(
                Key={'taskId': task_id},
                UpdateExpression="SET taskStatus = :s, failureReason = :r",
                ConditionExpression="attribute_not_exists(taskStatus) OR taskStatus <> :c",
                ExpressionAttributeValues={
                    ':s': 'FAILED',
                    ':r': 'A chunk failed processing after multiple retries.',
                    ':c': 'COMPLETED'
                }
            )

            print(f"Invoking packager/cleaner for failed task {task_id}.")
            lambda_client.invoke(
                FunctionName=SINGLE_FILE_PACKAGER_NAME,
                InvocationType='Event',
                Payload=json.dumps({'taskId': task_id})
            )

        except Exception as e:
            print(f"CRITICAL: Error in FailureHandler itself for message: {record['body']}. Error: {e}")
            raise e
            
    return {'statusCode': 200, 'body': 'DLQ batch processed.'}
