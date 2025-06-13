# getTaskStatus/lambda_function.py
import json
import boto3
import os
from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o)
        return super(DecimalEncoder, self).default(o)

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE_NAME'])

def lambda_handler(event, context):
    task_id = event['queryStringParameters'].get('taskId')
    
    if not task_id:
        return {'statusCode': 400, 'body': json.dumps('Missing taskId')}
        
    try:
        response = table.get_item(Key={'taskId': task_id})
        item = response.get('Item', {})
        
        return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(item, cls=DecimalEncoder)
        }
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps(str(e))}