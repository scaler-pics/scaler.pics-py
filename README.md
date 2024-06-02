# Scaler

A Python library for image scaling and conversion.

## Installation

```sh
pip install scaler-pics
```

## Usage

```python
from scaler-pics import Scaler, TransformOptions, InputOptions, OutputOptions, Fit, ImageDelivery

# Initialize the Scaler instance with the API key
scaler = Scaler(api_key='your_api_key')

# Define the transform options
options = TransformOptions(
    input=InputOptions(localPath='path/to/image.heic'),
    output=OutputOptions(
        type='jpeg',
        fit=Fit(width=1024, height=1024),
        imageDelivery=ImageDelivery(saveToLocalPath='path/to/output.jpg'),
        quality=0.8
    )
)

# Perform the transformation
response = scaler.transform(options)
print(response)
```
