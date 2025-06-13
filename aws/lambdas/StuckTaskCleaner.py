# StuckTaskCleaner/lambda_function.py
import boto3
import os
import time

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE_NAME'])
SINGLE_FILE_PACKAGER_NAME = os.environ['SINGLE_FILE_PACKAGER_NAME']

STUCK_THRESHOLD_SECONDS = 2 * 60 * 60 

def lambda_handler(event, context):
    print("Starting stuck task cleanup process...")

    response = table.query(
        IndexName='StatusIndex',
        KeyConditionExpression='taskStatus = :status',
        ExpressionAttributeValues={':status': 'PROCESSING'}
    )

    stuck_tasks = []
    current_time = int(time.time())

    for item in response.get('Items', []):
        task_id = item['taskId']
        creation_time = item.get('creationTime', 0)

        if (current_time - creation_time) > STUCK_THRESHOLD_SECONDS:
            stuck_tasks.append(item)
            print(f"Found stuck task: {task_id}, created at {creation_time}.")

    if not stuck_tasks:
        print("No stuck tasks found.")
        return

    for task in stuck_tasks:
        task_id = task['taskId']
        print(f"Marking task {task_id} as FAILED due to timeout.")
        table.update_item(
            Key={'taskId': task_id},
            UpdateExpression="SET taskStatus = :s, failureReason = :r",
            ExpressionAttributeValues={
                ':s': 'FAILED',
                ':r': 'Task timed out and was cleaned by sweeper.'
            }
        )
        lambda_client.invoke(
            FunctionName=SINGLE_FILE_PACKAGER_NAME,
            InvocationType='Event',
            Payload=json.dumps({'taskId': task_id})
        )

    print(f"Processed {len(stuck_tasks)} stuck tasks.")