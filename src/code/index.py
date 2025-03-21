import json
import os
import uuid
import logging
from urllib.parse import urlparse
import zipfile
import requests
from pdf2image import convert_from_path
import oss2
from PIL import Image

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 设置PIL的最大像素限制
Image.MAX_IMAGE_PIXELS = 1000000000

# OSS 配置
OSS_SECURITY_TOKEN = os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN")
OSS_ACCESS_KEY_ID = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
OSS_ACCESS_KEY_SECRET = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT")
OSS_BUCKET = os.getenv("OSS_BUCKET")

def download_pdf(url, local_path):
    """从给定URL下载PDF文件"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"PDF downloaded successfully to {local_path}")
    except requests.RequestException as e:
        logger.error(f"Error downloading PDF: {str(e)}")
        raise

def convert_pdf_to_images(pdf_path, output_dir, dpi=200):
    """将PDF转换为图像"""
    try:
        pages = convert_from_path(pdf_path, dpi=dpi)
        image_paths = []
        for i, page in enumerate(pages):
            image_path = os.path.join(output_dir, f"page_{i+1}.jpg")
            page.save(image_path, 'JPEG')
            image_paths.append(image_path)
        logger.info(f"Converted {len(pages)} pages to images")
        return image_paths
    except Exception as e:
        logger.error(f"Error converting PDF to images: {str(e)}")
        raise

def create_zip(zip_path, files):
    """创建包含给定文件的zip文件"""
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                zipf.write(file, os.path.basename(file))
        logger.info(f"Created zip file at {zip_path}")
    except Exception as e:
        logger.error(f"Error creating zip file: {str(e)}")
        raise

def upload_to_oss(bucket, local_file, object_name):
    """上传文件到OSS"""
    try:
        bucket.put_object_from_file(object_name, local_file)
        logger.info(f"Uploaded {local_file} to OSS as {object_name}")
    except oss2.exceptions.OssError as e:
        logger.error(f"Error uploading to OSS: {str(e)}")
        raise

def generate_presigned_url(bucket, object_name, expiration=3600):
    """生成OSS对象的预签名URL"""
    try:
        url = bucket.sign_url('GET', object_name, expiration)
        logger.info(f"Generated presigned URL for {object_name}")
        return url
    except oss2.exceptions.OssError as e:
        logger.error(f"Error generating presigned URL: {str(e)}")
        raise

def handler(event, context):
    try:
        # 解析输入
        evt = json.loads(event)
        print(evt)
        print(context)
        query_parameters = evt.get('queryParameters', {})
        pdf_url = query_parameters.get('pdf_url')
        if not pdf_url:
            raise ValueError("PDF URL is required")
        
        # 设置OSS客户端
        auth = oss2.StsAuth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_SECURITY_TOKEN)
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)

        # 创建临时目录
        tmp_dir = '/tmp'
        images_dir = os.path.join(tmp_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)

        # 下载PDF
        pdf_path = os.path.join(tmp_dir, 'input.pdf')
        download_pdf(pdf_url, pdf_path)

        # 转换PDF为图像
        image_paths = convert_pdf_to_images(pdf_path, images_dir, dpi=evt.get('dpi', 200))

        # 创建zip文件
        zip_path = os.path.join(tmp_dir, 'output.zip')
        create_zip(zip_path, image_paths)

        # 上传到OSS
        object_name = f"pdf_images_{uuid.uuid4()}.zip"
        upload_to_oss(bucket, zip_path, object_name)

        # 生成预签名URL
        presigned_url = generate_presigned_url(bucket, object_name)

        # 清理临时文件
        os.remove(pdf_path)
        for image_path in image_paths:
            os.remove(image_path)
        os.remove(zip_path)

        return {
            "code": "Success",
            "message": "PDF processed successfully",
            "presigned_url": presigned_url
        }

    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        return {
            "code": "Error",
            "message": str(e)
        }

