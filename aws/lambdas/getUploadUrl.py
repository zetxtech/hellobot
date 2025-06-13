# getUploadUrl/lambda_function.py
import json
import boto3
import os
import time

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE_NAME'])
UPLOAD_BUCKET = os.environ['UPLOAD_BUCKET']

def lambda_handler(event, context):
    body = json.loads(event.get('body', '{}'))
    task_id = body.get('taskId')
    filename = body.get('filename')
    content_type = body.get('contentType', 'application/octet-stream')

    if not task_id or not filename:
        return {'statusCode': 400, 'body': json.dumps('Missing taskId or filename')}
    
    table.put_item(
        Item={
            'taskId': task_id,
            'originalFilename': filename,
            'taskStatus': 'PENDING',
            'creationTime': int(time.time())
        }
    )
    
    object_key = f"{task_id}/{filename}"
    
    post_data = s3_client.generate_presigned_post(
        Bucket=UPLOAD_BUCKET,
        Key=object_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type}
        ],
        ExpiresIn=3600
    )

    return {
        'statusCode': 200,
        'headers': {'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json'},
        'body': json.dumps(post_data)
    }