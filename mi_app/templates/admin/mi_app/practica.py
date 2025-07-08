alfabeto = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']

def cifrado_cesar(texto, desplazamiento):
    texto_cifrado = ""
    for letra in texto:
        if letra in alfabeto:
            indice = alfabeto.index(letra)
            nuevo_indice = (indice + desplazamiento) % len(alfabeto)
            texto_cifrado += nuevo_indice[alfabeto]
        
        elif letra is [' ',',','.',':']:
            texto_cifrado += letra
        
        else:
            return "Todos los caracteres deben estar en mayúsculas y dentro del alfabeto."
    return texto_cifrado
            

def descifrado_cesar(texto_cifrado, desplazamiento):
    texto_descifrado = ""
    for letra in texto_cifrado:
        if letra in alfabeto:
            indice = alfabeto.index(letra)
            nuevo_indice = (indice - desplazamiento) % len(alfabeto)
            texto_cifrado += nuevo_indice[alfabeto]
        
        elif letra is [' ',',','.',':']:
            texto_cifrado += letra
        
        else:
            return "Todos los caracteres deben estar en mayúsculas y dentro del alfabeto."
    return texto_descifrado
    
texto = "SANTIAGO"
desplazamiento = 8

texto_cifrado = cifrado_cesar(texto,desplazamiento)
print(f"Texto cifrado: {texto_cifrado}")
texto_descifrado = descifrado_cesar(texto_cifrado, desplazamiento)
print(f"Texto descifrado: {texto_descifrado}")

texto_con_minusculas = "santiago"
resultado = cifrado_cesar(texto_con_minusculas,desplazamiento)
print(f"Texto con minusculas: {resultado}")