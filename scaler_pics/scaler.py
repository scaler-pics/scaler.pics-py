import jwt
import requests
import os
import time
from typing import List, Union, Optional
from io import BytesIO
import aiohttp
import asyncio


class ApiOutput:
    def __init__(self, fit, type, quality=None, upload=None, crop=None):
        self.fit = fit
        self.type = type
        self.quality = quality
        self.upload = upload
        self.crop = crop

    def to_dict(self):
        return {
            "fit": self.fit.to_dict(),
            "type": self.type,
            "quality": self.quality,
            "upload": self.upload,
            "crop": self.crop
        }


class ApiTransformOptions:
    def __init__(self, input, output: List[ApiOutput]):
        self.input = input
        self.output = output

    def to_dict(self):
        return {
            "input": self.input,
            "output": [out.to_dict() for out in self.output]
        }


class TransformResponse:
    def __init__(self, inputImage, outputImage, timeStats):
        self.inputImage = inputImage
        self.outputImage = outputImage
        self.timeStats = timeStats

    def to_dict(self):
        return {
            "inputImage": self.inputImage,
            "outputImage": self.outputImage,
            "timeStats": self.timeStats
        }


class PromiseResolvers:
    def __init__(self, resolve, reject):
        self.resolve = resolve
        self.reject = reject


class TransformOptions:
    def __init__(self, input, output=None):
        self.input = input
        self.output = output


class InputOptions:
    def __init__(self, remoteUrl=None, localPath=None, buffer=None):
        self.remoteUrl = remoteUrl
        self.localPath = localPath
        self.buffer = buffer


class ImageDelivery:
    def __init__(self, saveToLocalPath=None, upload=None, buffer=False):
        self.saveToLocalPath = saveToLocalPath
        self.upload = upload
        self.buffer = buffer


class Fit:
    def __init__(self, width, height, upscale=False):
        self.width = width
        self.height = height
        self.upscale = upscale

    def to_dict(self):
        return {
            "width": self.width,
            "height": self.height,
            "upscale": self.upscale
        }


class OutputOptions:
    def __init__(self, fit, type, quality=None, imageDelivery=None, crop=None):
        self.fit = fit
        self.type = type
        self.quality = quality
        self.imageDelivery = imageDelivery
        self.crop = crop


class OutputImage:
    def __init__(self, fit, pixelSize, image):
        self.fit = fit
        self.pixelSize = pixelSize
        self.image = image


class Scaler:
    def __init__(self, apiKey):
        self.apiKey = apiKey
        self.accessToken = None
        self.isRefreshingAccessToken = False
        self.refreshPromises = []

    async def transform(self, options: TransformOptions) -> TransformResponse:
        async with aiohttp.ClientSession() as session:
            await self.refreshAccessTokenIfNeeded(session)
            start = time.time()
            if not options.output:
                raise ValueError('No output provided')

            outs = options.output if isinstance(
                options.output, list) else [options.output]
            outputs = [ApiOutput(out.fit, out.type, out.quality, out.imageDelivery.upload if out.imageDelivery and hasattr(
                out.imageDelivery, 'upload') else None, out.crop) for out in outs]
            options2 = ApiTransformOptions(
                options.input.remoteUrl or 'body', outputs)

            startSignUrl = time.time()
            async with session.post(signUrl, headers={
                'Authorization': f'Bearer {self.accessToken}',
                'Content-Type': 'application/json'
            }, json=options2.to_dict()) as res:
                if res.status != 200:
                    text = await res.text()
                    raise ValueError(
                        f'Failed to get transform url. status: {res.status}, text: {text}')
                json = await res.json()
                signMs = (time.time() - startSignUrl) * 1000
                url = json['url']

                headers = {}
                body = None

                if options.input.buffer:
                    headers['Content-Type'] = 'application/octet-stream'
                    buffer = options.input.buffer
                    headers['Content-Length'] = str(len(buffer))
                    body = buffer
                elif options.input.localPath:
                    headers['Content-Type'] = 'application/octet-stream'
                    with open(options.input.localPath, 'rb') as f:
                        body = f.read()
                    headers['Content-Length'] = str(len(body))

                startTransformTime = time.time()
                async with session.post(url, headers=headers, data=body) as res2:
                    if res2.status != 200:
                        text = await res2.text()
                        raise ValueError(
                            f'Failed to transform image. status: {res2.status}, text: {text}')
                    transformResponse = await res2.json()

            endTransformTime = time.time()
            inputApiImage = transformResponse['inputImage']
            outputApiImages = transformResponse['outputImages']
            deleteUrl = transformResponse['deleteUrl']
            apiTimeStats = transformResponse['timeStats']
            sendImageMs = (endTransformTime - startTransformTime) * 1000 - \
                apiTimeStats['transformMs'] - \
                apiTimeStats.get('uploadImagesMs', 0)
            startGetImages = time.time()

            promises = []
            for i, dest in enumerate(outputApiImages):
                if dest['downloadUrl']:
                    dlUrl = dest['downloadUrl']
                    if outs[i].imageDelivery and outs[i].imageDelivery.saveToLocalPath:
                        destPath = outs[i].imageDelivery.saveToLocalPath
                        promises.append(self.download_to_local_path(
                            session, dlUrl, destPath))
                    else:
                        promises.append(
                            self.download_to_buffer(session, dlUrl))
                else:
                    promises.append(asyncio.Future().set_result('uploaded'))

            outputImageResults = await asyncio.gather(*promises)
            getImagesMs = (time.time() - startGetImages) * 1000

            deleteBody = {'images': [dest['fileId']
                                     for dest in outputApiImages if dest.get('fileId')]}
            async with session.delete(deleteUrl, headers={'Content-Type': 'application/json'}, json=deleteBody) as res:
                pass

            totalMs = (time.time() - start) * 1000
            outputImages = [OutputImage(dest['fit'], dest['pixelSize'], outputImageResults[i])
                            for i, dest in enumerate(outputApiImages)]

            response = TransformResponse(inputApiImage, outputImages if isinstance(options.output, list) else outputImages[0], {
                'signMs': signMs,
                'sendImageMs': sendImageMs,
                'transformMs': apiTimeStats['transformMs'],
                'getImagesMs': getImagesMs,
                'totalMs': totalMs
            })
            return response

    async def refreshAccessTokenIfNeeded(self, session):
        shouldRefresh = False
        if not self.accessToken:
            shouldRefresh = True
        else:
            decoded = jwt.decode(self.accessToken, options={
                                 "verify_signature": False})
            now = time.time()
            if now >= decoded['exp']:
                shouldRefresh = True

        if not shouldRefresh:
            return

        if self.isRefreshingAccessToken:
            future = asyncio.get_event_loop().create_future()
            self.refreshPromises.append(future)
            await future
            return

        self.isRefreshingAccessToken = True
        try:
            async with session.post(refreshAccessTokenUrl, headers={'Authorization': f'Bearer {self.apiKey}'}) as res:
                if res.status != 200:
                    text = await res.text()
                    raise ValueError(
                        f'Failed to refresh the access token. status: {res.status}, text: {text}')
                json = await res.json()
                self.accessToken = json['accessToken']
                for future in self.refreshPromises:
                    future.set_result(None)
                self.refreshPromises = []
                self.isRefreshingAccessToken = False
        except Exception as e:
            for future in self.refreshPromises:
                future.set_exception(e)
            self.refreshPromises = []
            self.isRefreshingAccessToken = False
            raise e

    async def download_to_local_path(self, session, dlUrl, destPath):
        async with session.get(dlUrl) as res:
            if res.status != 200:
                text = await res.text()
                raise ValueError(
                    f'Failed to download image. status: {res.status}, text: {text}')
            with open(destPath, 'wb') as f:
                while True:
                    chunk = await res.content.read(1024)
                    if not chunk:
                        break
                    f.write(chunk)
        return destPath

    async def download_to_buffer(self, session, dlUrl):
        async with session.get(dlUrl) as res:
            if res.status != 200:
                text = await res.text()
                raise ValueError(
                    f'Failed to download image. status: {res.status}, text: {text}')
            return await res.read()


# Environment Variables
refreshAccessTokenUrl = os.getenv(
    'REFRESH_URL', 'https://api.scaler.pics/auth/api-key-token')
signUrl = os.getenv('SIGN_URL', 'https://sign.scaler.pics/sign')

__all__ = ['Scaler', 'TransformOptions', 'InputOptions', 'OutputOptions',
           'ImageDelivery', 'Fit', 'OutputImage', 'TransformResponse']
