const unites = ['', 'un', 'deux', 'trois', 'quatre', 'cinq', 'six', 'sept', 'huit', 'neuf']
const dizaines = ['', '', 'vingt', 'trente', 'quarante', 'cinquante', 'soixante', 'soixante', 'quatre-vingt', 'quatre-vingt']
const exceptions = ['dix', 'onze', 'douze', 'treize', 'quatorze', 'quinze', 'seize', 'dix-sept', 'dix-huit', 'dix-neuf']

function convertirPartieEntiere(n: number): string {
  if (n === 0) return 'zéro'
  if (n < 0) return 'moins ' + convertirPartieEntiere(-n)

  let result = ''

  if (n >= 1000000000) {
    const milliards = Math.floor(n / 1000000000)
    result += convertirPartieEntiere(milliards) + ' milliard' + (milliards > 1 ? 's' : '') + ' '
    n %= 1000000000
  }

  if (n >= 1000000) {
    const millions = Math.floor(n / 1000000)
    result += convertirPartieEntiere(millions) + ' million' + (millions > 1 ? 's' : '') + ' '
    n %= 1000000
  }

  if (n >= 1000) {
    const milliers = Math.floor(n / 1000)
    if (milliers === 1) {
      result += 'mille '
    } else {
      result += convertirPartieEntiere(milliers) + ' mille '
    }
    n %= 1000
  }

  if (n >= 100) {
    const centaines = Math.floor(n / 100)
    if (centaines === 1) {
      result += 'cent '
    } else {
      result += unites[centaines] + ' cent '
    }
    n %= 100
    if (n === 0 && centaines > 1 && result.endsWith('cent ')) {
      result = result.slice(0, -1) + 's '
    }
  }

  if (n >= 20) {
    const diz = Math.floor(n / 10)
    const unite = n % 10

    if (diz === 7 || diz === 9) {
      result += dizaines[diz] + '-'
      if (diz === 7) {
        result += exceptions[unite]
      } else {
        if (unite === 0) {
          result += 'dix'
        } else {
          result += exceptions[unite]
        }
      }
    } else {
      result += dizaines[diz]
      if (unite === 1 && diz !== 8) {
        result += ' et un'
      } else if (unite > 0) {
        result += '-' + unites[unite]
      } else if (diz === 8) {
        result += 's'
      }
    }
  } else if (n >= 10) {
    result += exceptions[n - 10]
  } else if (n > 0) {
    result += unites[n]
  }

  return result.trim()
}

export function numberToWords(amount: number): string {
  if (isNaN(amount)) return ''

  const partieEntiere = Math.floor(Math.abs(amount))
  const partieDecimale = Math.round((Math.abs(amount) - partieEntiere) * 100)

  let resultat = convertirPartieEntiere(partieEntiere)

  if (resultat === '') {
    resultat = 'zéro'
  }

  resultat = resultat.charAt(0).toUpperCase() + resultat.slice(1)

  if (partieDecimale > 0) {
    resultat += ' dollars américains et ' + convertirPartieEntiere(partieDecimale) + ' cents'
  } else {
    resultat += ' dollars américains'
  }

  return resultat
}
