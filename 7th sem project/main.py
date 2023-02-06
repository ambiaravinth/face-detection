import io
import os
import cv2
import boto3
import numpy as np
import pandas as pd
from PIL import Image
import boto3 as boto3
import mysql.connector
from datetime import date
from base64 import b64encode
from datetime import datetime
from IPython.display import display
from werkzeug.utils import secure_filename
from flask import Flask, request, render_template, jsonify, redirect, Response


# Defining Flask App
app = Flask(__name__)


# To get invoke the home page... 
@app.route('/')
def home():
    # Get date and Time...
    today_dat = date.today().strftime("%d/%m/%Y")
    today_time = datetime.now().strftime("%H:%M")
    
    #Get connection to MySql...     
    connection = mysql.connector.connect(host='localhost', database='face', user='root', password='')
    cursor = connection.cursor()
    
    #Get How many data from authorized table...
    sql_fetch_blob_query = """SELECT COUNT(*) from face_data_auth"""
    cursor.execute(sql_fetch_blob_query)
    auth_record = cursor.fetchall()
    for row in auth_record:
        auth_count = row[0]
    
    #Get How many data in Unauthorized table...
    sql_fetch_blob_query = """SELECT COUNT(*) from face_data_unauth"""
    cursor.execute(sql_fetch_blob_query)
    unauth_record = cursor.fetchall()
    for row in unauth_record:
        unauth_count = row[0]
    
    print("Date = ", today_dat)
    print("Time = ", today_time)
    print("Authorized person count = ", auth_count)
    print("Unauthorized person count = ", unauth_count)
        
    return render_template('index.html', today_dat = today_dat, today_time = today_time, auth_count = auth_count, unauth_count = unauth_count)


#TO get a live video stream... 
def generate_frames():
    #capture the live video footage...
    # capture = cv2.VideoCapture('aaa.mp4')
    capture = cv2.VideoCapture(0)
    
    while True:
        bollean, frame = capture.read()
        
        # Convert into grayscale...
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Load the cascade...
        # face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')
        face_cascade = cv2.CascadeClassifier('haarcascade_profileface.xml')
        
        # Detect faces...
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        # Draw rectangle around the faces and crop the faces...
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x-50, y-50), (x+w+30, y+h+30), (0, 0, 255), 1)
            
            # crop a gace image...
            finimg = frame[y-50:y+h+30, x-50:x+w+30]
            
            # compare this image with AWS Rekognition face images...
            cmpface(finimg)
        
        # load to the buffer and send it to HTML...
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


#To compare the real time image to AWS images...
def cmpface(finimg):
    try:
        # save in local storage...
        cv2.imwrite("test.jpg", finimg) 
        
        # Rekongnition service config... 
        rekognition = boto3.client('rekognition', region_name='us-east-1')
        dynamodb = boto3.client('dynamodb', region_name='us-east-1')
        
        # Convert into binary image formate...
        image = Image.open('test.jpg')
        stream = io.BytesIO()
        image.save(stream, format="JPEG")
        image_binary = stream.getvalue()
    
        # Get responce from Rekognition service...
        response = rekognition.search_faces_by_image(CollectionId='famouspersons', Image={'Bytes': image_binary})
        
        # Check Authorized person or NOT by compare all faceprints...
        found = False
        for match in response['FaceMatches']:
            print(match['Face']['FaceId'], match['Face']['Confidence'])
            face = dynamodb.get_item(TableName='face_recognition', Key={'RekognitionId': {'S': match['Face']['FaceId']}})
            
            # If Found person or matches faceprint...
            if 'Item' in face:
                # get deatails of the faceprints...
                print("Found Person: ", face['Item']['FullName']['S'])
                name=str(face['Item']['FullName']['S'])
                
                found = True
                try:
                    # SQL database config...
                    connection = mysql.connector.connect(host='localhost', database='face', user='root', password='')
                    cursor = connection.cursor()
                    sql_insert_query = """INSERT INTO face_data_auth(username, photo) VALUES (%s,%s)"""
                    
                    # Convert data into tuple format and push it to cloud...
                    insert_tuple = (name, image_binary)
                    result = cursor.execute(sql_insert_query, insert_tuple)
                    connection.commit()
                    print("Image inserted successfully...", result)
                
                # Get wether any issue arrise...
                except mysql.connector.Error as error:
                    print("Failed inserting Image... {}".format(error))
                
                # close the Connection from SQL database...
                finally:
                    if connection.is_connected():
                        cursor.close()
                        connection.close()
                        print("MySQL connection is closed...")
                    home()
        
        # If cannot found a person or not maches faceprints...
        if not found:
            print("Person cannot be recognized")
            name = "unauthorized"
            try:
                # SQL database config...
                connection = mysql.connector.connect(host='localhost', database='face', user='root', password='')
                cursor = connection.cursor()
                sql_insert_query = """INSERT INTO face_data_unauth(username, photo) VALUES (%s,%s)"""
                
                # Convert data into tuple format and push it to cloud...
                insert_tuple = (name, image_binary)
                result = cursor.execute(sql_insert_query, insert_tuple)
                connection.commit()
                print("Image and file inserted successfully...", result)
            
            # Get wether any issue arrise...
            except mysql.connector.Error as error:
                print("Failed inserting BLOB data into MySQL table {}".format(error))
            
            # close the Connection from SQL database...
            finally:
                if connection.is_connected():
                    cursor.close()
                    connection.close()
                    print("MySQL connection is closed...")
                    home()
    except:
        print("No faces found...")


#to get a new name for upload image to S3 bucket...
def newname():
    bucket = "ambi-persons-images"
    folder = "index"
    s3 = boto3.resource("s3") 
    s3_bucket = s3.Bucket(bucket)
    files_in_s3 = [f.key.split(folder + "/")[1] for f in s3_bucket.objects.filter(Prefix=folder).all()]
    count = len(files_in_s3)+1
    name="image_"+str(count)+".jpg"
    return name


# Upload to the AWS S3 Bucket...
@app.route('/sent', methods=['GET', 'POST'])
def sent():
    
    # Get user name...
    newusername = request.form['newusername']
    if request.method == "POST":
        
        # Get user Image...
        image = request.files['newuserimages']
        if image.filename == '':
            print("Image must have a file name")
            return redirect(request.url)
        
        # Save the image...
        newimgname=newname()
        image.save(newimgname)
        
        # Get list of objects for indexing
        images = [(newimgname, newusername)]
        
        # Iterate through list to upload objects to S3
        s3 = boto3.resource('s3')
        for img in images:
            file = open(img[0], 'rb')
            object = s3.Object('ambi-persons-images', 'index/' + img[0])
            ret = object.put(Body=file, Metadata={'FullName': img[1]})
        return render_template('index.html')
    
    return render_template('addperson.html')


# Authorized persons management...
@app.route('/auth')
def auth():
    try:
        # Get a connection from SQL....
        connection = mysql.connector.connect(host='localhost', database='face', user='root', password='')
        cursor = connection.cursor()
        sql_fetch_blob_query = """SELECT * from face_data_auth"""
        cursor.execute(sql_fetch_blob_query)
        record = cursor.fetchall()
        
        # Get all the data from database...
        for row in record:
            # print("Id = ", row[0], )
            # print("Name = ", row[1])
            # print("image = ", row[2])
            # print("date and time = ", row[3])
            Name = row[1]
            with open("db_img.jpg", 'wb') as file:
                file.write(row[2])
            
            # Get new file name...
            imgname="auth_face_"+Name+".jpg"
            
            # Get new dir file or create...    
            if not os.path.isdir('static'):
                os.makedirs('static')
            
            # store in local...    
            img = cv2.imread("db_img.jpg")
            cv2.imwrite('static/'+imgname, img)
        
        # Send to html file...        
        return render_template('auth.html',result=record)
    
    # check any issue will arrise...
    except mysql.connector.Error as error:
        print("Failed to read data from MySQL... {}".format(error))
        return render_template('auth.html',result=record)
    
    # Close the connection...
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
            print("MySQL connection is closed")
            return render_template('auth.html',result=record)


# Unauthorized persons management...
@app.route('/unauth')
def unauth():
    try:
        # Get a connection from SQL....
        connection = mysql.connector.connect(host='localhost', database='face', user='root', password='')
        cursor = connection.cursor()
        sql_fetch_blob_query = """SELECT * from face_data_unauth"""
        cursor.execute(sql_fetch_blob_query)
        record = cursor.fetchall()
        
        Number = 1
        # Get all the data from database...
        for row in record:
            # print("Id = ", row[0], )
            # print("Name = ", row[1])
            # print("image = ", row[2])
            # print("date and time = ", row[3])
            
            with open("db_img.jpg", 'wb') as file:
                file.write(row[2])
            
            # Get new file name...
            imgname="unauth_face_"+str(Number)+".jpg"
            Number=Number+1
            # Get new dir file or create...    
            if not os.path.isdir('static'):
                os.makedirs('static')
            
            # store in local...    
            img = cv2.imread("db_img.jpg")
            cv2.imwrite('static/'+imgname, img)   
    
    except mysql.connector.Error as error:
        print("Failed to read BLOB data from MySQL table {}".format(error))
    
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
            print("MySQL connection is closed")
    return render_template('unauth.html', result=record)


@app.route('/addperson')
def addperson():
    return render_template('addperson.html')


@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


# Our main function which runs the Flask App
if __name__ == '__main__':
    app.run(debug=True)